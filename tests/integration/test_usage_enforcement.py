import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from google.genai import types

from app.core.errors import AppError
from app.db.models import DailyUsage, UsageReservation, User
from app.db.models import Conversation
from app.db.base import utcnow
from app.main import create_app
from app.services import conversations
from app.repositories import usage_limits
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeProvider, settings
from tests.helpers.recovery_provider import RecoveryConnection


class UnfinishedTurnConnection(RecoveryConnection):
    async def send_audio(self, data):
        if not self.audio:
            return await super().send_audio(data)
        self.audio.append(data)
        # This response is billable activity after the last finalized usage event.
        await self.queue.put(types.LiveServerMessage(server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(
                data=b'\0\0' * 240, mime_type='audio/pcm;rate=24000',
            ))]),
        )))


class UnfinishedTurnProvider:
    @asynccontextmanager
    async def connect(self, prompt, *, resume_handle=None):
        self.connection = UnfinishedTurnConnection()
        try:
            yield self.connection
        finally:
            self.connection.closed = True


def make_client(**overrides):
    return FoundationClient(create_app(settings(**overrides), FakeProvider()))


def create_conversation(client):
    response = client.post('/api/v1/conversations', json={})
    assert response.status_code == 201, response.text
    return response.json()


def test_usage_status_and_live_settlement_are_owner_scoped_and_idempotent():
    with make_client() as client:
        before = client.get('/api/v1/usage/me').json()
        assert before['connected_seconds'] == 0
        assert before['available_seconds'] == 900
        conversation = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': conversation['id']})
            ready = socket.receive_json()
            assert ready['type'] == 'ready' and ready['max_seconds'] == 300
            socket.send_json({'type': 'stop'})
            report = socket.receive_json()['report']
        assert report['allowance_reserved_seconds'] == 300
        after = client.get('/api/v1/usage/me').json()
        assert 0 <= after['connected_seconds'] <= 300
        assert after['reserved_seconds'] == 0
        assert after['sessions_started'] == after['sessions_settled'] == 1

        async def inspect():
            async with client.database.sessions.begin() as session:
                await usage_limits.settle(session, UUID(conversation['id']), 999, 999, True)
                reservation = await session.get(UsageReservation, UUID(conversation['id']))
                daily = await session.scalar(select(DailyUsage))
                assert reservation.status == 'settled'
                assert daily.sessions_settled == 1
        client.portal.call(inspect)


def test_allowance_is_reserved_atomically_before_provider_admission():
    with make_client(session_max_seconds=40, minimum_session_seconds=30,
                     daily_connected_seconds=60) as client:
        first, second = create_conversation(client), create_conversation(client)

        async def claim_both():
            async with client.database.sessions() as session:
                user = await session.scalar(select(User).where(User.email == 'default@example.com'))
            _, _, allocation = await conversations.claim(
                client.database, user.id, UUID(first['id']), runtime_owner='first', lease_seconds=30,
                settings=client.app.state.settings, include_allocation=True,
            )
            assert allocation.seconds == 40
            with pytest.raises(AppError) as denied:
                async with client.database.sessions.begin() as session:
                    await usage_limits.reserve(session, user.id, UUID(second['id']), client.app.state.settings)
            assert denied.value.code == 'daily_allowance_exhausted'
        client.portal.call(claim_both)


def test_expired_runtime_conservatively_settles_full_reservation():
    with make_client(session_max_seconds=40, minimum_session_seconds=30,
                     daily_connected_seconds=60) as client:
        conversation = create_conversation(client)

        async def abandon_and_recover():
            async with client.database.sessions() as session:
                user = await session.scalar(select(User).where(User.email == 'default@example.com'))
            claimed, _, _ = await conversations.claim(
                client.database, user.id, UUID(conversation['id']), runtime_owner='lost', lease_seconds=30,
                settings=client.app.state.settings, include_allocation=True,
            )
            async with client.database.sessions.begin() as session:
                await session.execute(update(Conversation).where(Conversation.id == claimed.id).values(
                    lease_expires_at=utcnow() - timedelta(seconds=1)))
            await client.app.state.sessions.maintain_once()
        client.portal.call(abandon_and_recover)
        status = client.get('/api/v1/usage/me').json()
        assert status['connected_seconds'] == 40
        assert status['reserved_seconds'] == 0
        assert status['sessions_settled'] == 1


def test_conversation_creation_rate_limit_is_atomic():
    with make_client(conversation_creations_per_hour=2) as client:
        assert client.post('/api/v1/conversations', json={}).status_code == 201
        assert client.post('/api/v1/conversations', json={}).status_code == 201
        denied = client.post('/api/v1/conversations', json={})
        assert denied.status_code == 429
        assert denied.json() == {'error': 'conversation_rate_limited'}


def test_disabled_creation_limit_bypasses_an_already_exhausted_window():
    with make_client(conversation_creations_per_hour=1) as client:
        assert client.post('/api/v1/conversations', json={}).status_code == 201
        assert client.post('/api/v1/conversations', json={}).status_code == 429
        client.app.state.settings.conversation_creations_per_hour = 0
        for _ in range(12):
            assert client.post('/api/v1/conversations', json={}).status_code == 201
        client.app.state.settings.conversation_creations_per_hour = 1
        assert client.post('/api/v1/conversations', json={}).status_code == 429


def test_cost_guard_stops_on_reported_threshold_and_settles_provider_estimate():
    with make_client(
        usage_mode='per_response', cost_guard_enabled=True,
        session_estimated_cost_limit_usd=Decimal('0.00005'),
        daily_estimated_cost_limit_usd=Decimal('0.00005'), cost_guard_margin_ratio=0,
    ) as client:
        conversation = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': conversation['id']})
            assert socket.receive_json()['type'] == 'ready'
            socket.send_bytes(b'\x01\x00' * 160)
            assert socket.receive_bytes()
            ended = socket.receive_json()
        assert ended['report']['end_reason'] == 'cost_limit'
        assert ended['report']['estimated_model_cost_usd'] == .00009
        usage = client.get('/api/v1/usage/me').json()
        assert Decimal(usage['estimated_cost_usd']) == Decimal('0.00009000')
        assert Decimal(usage['reserved_cost_usd']) == 0
        second = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': second['id']})
            denied = socket.receive_json()
        assert denied['code'] == 'daily_cost_limit_reached'


def test_admin_usage_requires_database_role_flag():
    with make_client() as client:
        assert client.get('/api/v1/admin/usage').status_code == 403

        async def grant():
            async with client.database.sessions.begin() as session:
                await session.execute(update(User).where(User.email == 'default@example.com').values(is_admin=True))
        client.portal.call(grant)
        response = client.get('/api/v1/admin/usage')
        assert response.status_code == 200
        assert response.json()['items'] == []


@pytest.mark.parametrize('receive_usage', [False, True])
def test_missing_provider_usage_stops_and_consumes_spend_reservation(receive_usage):
    with make_client(usage_mode='per_response', cost_guard_enabled=True,
                     cost_usage_timeout_seconds=.1) as client:
        conversation = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': conversation['id']})
            assert socket.receive_json()['type'] == 'ready'
            if receive_usage:
                socket.send_bytes(b'\x01\x00' * 160)
                assert socket.receive_bytes()
                assert socket.receive_json()['type'] == 'turn_complete'
            ended = socket.receive_json()['report']
        assert ended['end_reason'] == 'cost_tracking_unavailable'
        assert ended['estimated_model_cost_usd'] is None
        usage = client.get('/api/v1/usage/me').json()
        assert Decimal(usage['estimated_cost_usd']) == Decimal('0.20')
        assert Decimal(usage['reserved_cost_usd']) == 0
        assert usage['incomplete_cost_sessions'] == 1


@pytest.mark.parametrize('termination', ['socket_stop', 'http_stop', 'logout', 'shutdown',
                                         'provider_error', 'duration'])
def test_unreported_turn_settles_conservatively_on_every_terminal_path(termination):
    provider = UnfinishedTurnProvider()
    options = settings(usage_mode='per_response', cost_guard_enabled=True,
                       session_max_seconds=1 if termination == 'duration' else 300)
    with FoundationClient(create_app(options, provider)) as client:
        row = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': row['id']})
            assert socket.receive_json()['type'] == 'ready'
            socket.send_bytes(b'\x01\x00' * 160)
            assert socket.receive_bytes()
            assert socket.receive_json()['type'] == 'turn_complete'
            socket.send_bytes(b'\x01\x00' * 160)
            assert socket.receive_bytes()
            if termination == 'socket_stop':
                socket.send_json({'type': 'stop'})
            elif termination == 'http_stop':
                assert client.post(f'/api/v1/conversations/{row["id"]}/stop').status_code == 204
            elif termination == 'logout':
                assert client.post('/api/v1/auth/logout').status_code == 204
            elif termination == 'shutdown':
                client.portal.call(client.app.state.sessions.close)
            elif termination == 'provider_error':
                client.portal.call(provider.connection.queue.put, RuntimeError('simulated provider failure'))
            report = socket.receive_json()['report']
        assert report['estimated_model_cost_usd'] is None
        assert report['observed_model_cost_usd'] == .00009
        assert report['unreported_provider_activity'] is True
        assert report['usage_complete'] is False
        assert report['persisted'] is True

        async def inspect():
            async with client.database.sessions() as session:
                reservation = await session.get(UsageReservation, UUID(row['id']))
                daily = await session.scalar(select(DailyUsage))
                assert reservation.settled_cost_usd == Decimal('.20')
                assert reservation.cost_complete is False
                assert daily.incomplete_cost_sessions == 1
                assert daily.reserved_cost_usd == 0
        client.portal.call(inspect)


def test_completed_turn_releases_unused_spend_reservation():
    with make_client(usage_mode='per_response', cost_guard_enabled=True) as client:
        row = create_conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': row['id']})
            assert socket.receive_json()['type'] == 'ready'
            socket.send_bytes(b'\x01\x00' * 160)
            assert socket.receive_bytes()
            assert socket.receive_json()['type'] == 'turn_complete'
            socket.send_json({'type': 'stop'})
            report = socket.receive_json()['report']
        assert report['usage_complete'] is True
        usage = client.get('/api/v1/usage/me').json()
        assert Decimal(usage['estimated_cost_usd']) == Decimal('.00009')
        assert Decimal(usage['reserved_cost_usd']) == 0
        assert usage['incomplete_cost_sessions'] == 0


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Concurrent row locks require PostgreSQL')
def test_parallel_admission_cannot_overbook_daily_allowance():
    with make_client(session_max_seconds=40, minimum_session_seconds=30,
                     daily_connected_seconds=60) as client:
        first, second = create_conversation(client), create_conversation(client)

        async def race():
            async with client.database.sessions() as session:
                user = await session.scalar(select(User).where(User.email == 'default@example.com'))

            async def claim(identifier, owner):
                try:
                    async with client.database.sessions.begin() as session:
                        await usage_limits.reserve(session, user.id, UUID(identifier), client.app.state.settings)
                    return 'accepted'
                except AppError as exc:
                    return exc.code

            return await asyncio.gather(claim(first['id'], 'a'), claim(second['id'], 'b'))

        assert sorted(client.portal.call(race)) == ['accepted', 'daily_allowance_exhausted']


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Concurrent row locks require PostgreSQL')
def test_parallel_settlement_refreshes_reservation_after_lock_wait():
    with make_client() as client:
        conversation = create_conversation(client)

        async def race():
            async with client.database.sessions() as session:
                user = await session.scalar(select(User).where(User.email == 'default@example.com'))
            await conversations.claim(
                client.database, user.id, UUID(conversation['id']), runtime_owner='race',
                settings=client.app.state.settings, include_allocation=True,
            )
            both_loaded = asyncio.Event()
            loaded = 0

            async def settle():
                nonlocal loaded
                async with client.database.sessions.begin() as session:
                    # Preload the ORM object to reproduce a stale identity-map snapshot.
                    reservation = await session.get(UsageReservation, UUID(conversation['id']))
                    loaded += 1
                    if loaded == 2:
                        both_loaded.set()
                    await both_loaded.wait()
                    await usage_limits.settle(session, UUID(conversation['id']), 5, .01, True)

            await asyncio.gather(settle(), settle())
        client.portal.call(race)
        status = client.get('/api/v1/usage/me').json()
        assert status['connected_seconds'] == 5
        assert Decimal(status['estimated_cost_usd']) == Decimal('.01')
        assert status['sessions_settled'] == 1
        assert status['reserved_seconds'] == 0
