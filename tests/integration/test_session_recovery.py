import asyncio
import json
from datetime import timedelta
from time import monotonic
from uuid import UUID

import pytest
from google.genai import types
from google.genai.errors import APIError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.base import utcnow
from app.db.models import Conversation
from app.main import create_app
from app.repositories import conversations as repository
from app.services import conversations
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import settings, start
from tests.helpers.recovery_provider import RecoveryProvider


@pytest.fixture
def client():
    options = settings(session_max_seconds=4, session_idle_seconds=4,
                       client_reconnect_grace_seconds=.8, lease_seconds=3,
                       lease_heartbeat_seconds=.5)
    with FoundationClient(create_app(options, RecoveryProvider())) as value:
        yield value


def receive_event(ws, expected):
    while True:
        frame = ws.receive()
        if frame.get('bytes') is not None:
            continue
        event = json.loads(frame['text'])
        if event['type'] == expected:
            return event
        assert event['type'] not in {'error', 'ended'}, event


def emit(client, event):
    client.portal.call(client.app.state.provider.connections[-1].queue.put, event)


def goaway(client):
    emit(client, types.LiveServerMessage(go_away=types.LiveServerGoAway(time_left='10s')))


def wait_until(client, predicate, seconds=3):
    async def wait():
        async with asyncio.timeout(seconds):
            while not predicate():
                await asyncio.sleep(.01)
    client.portal.call(wait)


def test_goaway_resumes_same_session_without_audio_replay_or_secret_reports(client):
    provider = client.app.state.provider
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        started = client.portal.call(lambda: client.app.state.sessions.sessions[initial['session_id']].relay.measurements.started)
        first_audio = b'\xe8\x03' * 320
        ws.send_bytes(first_audio)
        receive_event(ws, 'turn_complete')
        goaway(client)
        receive_event(ws, 'reconnecting')
        resumed = receive_event(ws, 'resumed')
        assert resumed['session_id'] == initial['session_id']
        assert resumed['protocol_version'] == 3
        # On Windows a fast simulated reconnect can share a monotonic clock tick
        # with setup. Verify the original clock is retained without assuming a
        # strictly positive elapsed interval.
        assert resumed['remaining_seconds'] <= initial['remaining_seconds'] <= resumed['max_seconds']
        assert client.portal.call(lambda: client.app.state.sessions.sessions[initial['session_id']].relay.measurements.started) == started
        second_audio = b'\xd0\x07' * 320
        ws.send_bytes(second_audio)
        receive_event(ws, 'turn_complete')
        ws.send_json({'type': 'stop'})
        report = receive_event(ws, 'ended')['report']
    assert provider.handles == [None, 'PRIVATE_HANDLE_1']
    assert provider.connections[0].audio == [first_audio]
    assert provider.connections[1].audio == [second_audio]
    assert all(connection.closed for connection in provider.connections)
    assert report['provider_reconnect_count'] == 1
    assert report['resume_attempt_count'] == 1
    assert report['estimated_model_cost_usd'] is None
    assert 'PRIVATE_HANDLE' not in json.dumps(report)
    assert report['persisted']


def test_transient_network_error_resumes_checkpoint(client):
    with client.websocket_connect('/ws/live') as ws:
        start(ws)
        emit(client, ConnectionError('PRIVATE_PROVIDER_MESSAGE'))
        receive_event(ws, 'resumed')
        ws.send_json({'type': 'stop'})
        report = receive_event(ws, 'ended')['report']
        assert 'PRIVATE_PROVIDER_MESSAGE' not in json.dumps(report)


def test_invalidated_checkpoint_ends_without_fresh_context(client):
    with client.websocket_connect('/ws/live') as ws:
        start(ws)
        emit(client, types.LiveServerMessage(session_resumption_update=types.LiveServerSessionResumptionUpdate(resumable=False)))
        emit(client, ConnectionError('disconnected'))
        assert receive_event(ws, 'ended')['report']['end_reason'] == 'resume_unavailable'
    assert client.app.state.provider.handles == [None]


@pytest.mark.parametrize('failure, reason', [
    (APIError(400, {'message': 'PRIVATE_INVALID_HANDLE'}), 'resume_rejected'),
    (APIError(401, {'message': 'PRIVATE_INVALID_KEY'}), 'resume_rejected'),
])
def test_nonretryable_resume_failure_never_falls_back_to_new_session(client, failure, reason):
    client.app.state.provider.fail_resumes = [failure]
    with client.websocket_connect('/ws/live') as ws:
        start(ws)
        goaway(client)
        report = receive_event(ws, 'ended')['report']
        assert report['end_reason'] == reason
        assert report['resume_attempt_count'] == 1
        assert 'PRIVATE' not in json.dumps(report)
    assert client.app.state.provider.handles == [None, 'PRIVATE_HANDLE_1']


def test_retry_budget_is_finite_across_transient_setup_failures(client):
    client.app.state.provider.fail_resumes = [ConnectionError('temporary')] * 5
    with client.websocket_connect('/ws/live') as ws:
        start(ws)
        goaway(client)
        report = receive_event(ws, 'ended')['report']
        assert report['end_reason'] == 'resume_attempts_exhausted'
        assert report['resume_attempt_count'] == 3
    assert len(client.app.state.provider.handles) == 4
    assert all(handle is not None for handle in client.app.state.provider.handles[1:])


def test_app_reattachment_keeps_runtime_and_closes_provider_during_gap(client):
    provider = client.app.state.provider
    with client.websocket_connect('/ws/live') as first:
        initial = start(first)
        first.send_bytes(b'\xe8\x03' * 320)
        receive_event(first, 'turn_complete')
    wait_until(client, lambda: provider.connections[0].closed)
    assert client.app.state.active
    assert len(provider.connections) == 1
    with client.websocket_connect('/ws/live') as second:
        second.send_json({'type': 'start', 'conversation_id': initial['session_id']})
        resumed = receive_event(second, 'resumed')
        assert resumed['session_id'] == initial['session_id']
        second.send_json({'type': 'stop'})
        report = receive_event(second, 'ended')['report']
    assert report['client_reconnect_count'] == 1
    assert provider.handles == [None, 'PRIVATE_HANDLE_1']


def test_duplicate_attachment_does_not_disconnect_original(client):
    with client.websocket_connect('/ws/live') as first:
        initial = start(first)
        with client.websocket_connect('/ws/live') as duplicate:
            duplicate.send_json({'type': 'start', 'conversation_id': initial['session_id']})
            assert duplicate.receive_json()['code'] == 'conversation_already_attached'
        first.send_bytes(b'\xe8\x03' * 320)
        receive_event(first, 'turn_complete')
        first.send_json({'type': 'stop'})
        assert receive_event(first, 'ended')['report']['end_reason'] == 'user_stopped'


def test_new_login_token_cannot_take_over_existing_runtime(client):
    with client.websocket_connect('/ws/live') as first:
        initial = start(first)
        token = client.post('/api/v1/auth/login', json={
            'email': 'default@example.com', 'password': 'TestPassword123!',
        }).json()['access_token']
        with client.websocket_connect('/ws/live', headers={'authorization': f'Bearer {token}'}) as other:
            other.send_json({'type': 'start', 'conversation_id': initial['session_id']})
            assert other.receive_json()['code'] == 'resume_auth_session_mismatch'
        first.send_json({'type': 'stop'})
        receive_event(first, 'ended')


def test_reconnect_grace_expiration_releases_slot_and_finalizes(client):
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        # Ensure the checkpoint has been read before disconnecting.
        ws.send_bytes(b'\xe8\x03' * 320)
        receive_event(ws, 'turn_complete')
    wait_until(client, lambda: not client.app.state.active)
    report = client.get('/api/v1/conversations/' + initial['session_id'] + '/report').json()
    assert report['end_reason'] == 'client_reconnect_timeout'
    assert len(client.app.state.provider.connections) == 1


def test_http_stop_works_while_client_is_detached(client):
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        ws.send_bytes(b'\xe8\x03' * 320)
        receive_event(ws, 'turn_complete')
    assert client.post('/api/v1/conversations/' + initial['session_id'] + '/stop').status_code == 204
    wait_until(client, lambda: not client.app.state.active)
    assert client.get('/api/v1/conversations/' + initial['session_id'] + '/report').json()['end_reason'] == 'user_stopped'


def test_reconnection_does_not_reset_original_duration_deadline():
    options = settings(session_max_seconds=.45, client_reconnect_grace_seconds=.3)
    with FoundationClient(create_app(options, RecoveryProvider())) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws)
            client.portal.call(asyncio.sleep, .15)
            goaway(client)
            receive_event(ws, 'resumed')
            report = receive_event(ws, 'ended')['report']
            assert report['end_reason'] == 'duration_limit'
            assert report['duration_seconds'] < .8


def test_pings_do_not_renew_user_idle_timeout():
    with FoundationClient(create_app(settings(session_idle_seconds=.15), RecoveryProvider())) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws)
            ws.send_json({'type': 'ping'})
            receive_event(ws, 'pong')
            assert receive_event(ws, 'ended')['report']['end_reason'] == 'idle_timeout'


def test_expired_lease_recovery_is_fenced_and_does_not_invent_usage(client):
    row = client.post('/api/v1/conversations', json={}).json()
    user = client.get('/api/v1/users/me').json()

    async def expire_and_recover():
        conversation, _ = await conversations.claim(client.database, UUID(user['id']), UUID(row['id']), runtime_owner='dead_worker')
        async with client.database.sessions.begin() as session:
            await session.execute(update(Conversation).where(Conversation.id == conversation.id)
                                  .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        await client.app.state.sessions.maintain_once()
        async with client.database.sessions.begin() as session:
            assert await repository.renew(session, conversation.id, 'dead_worker', 30) is None
            assert not await repository.finish(session, conversation.id, {'end_reason': 'user_stopped'}, 'dead_worker')
    client.portal.call(expire_and_recover)
    stored = client.get('/api/v1/conversations/' + row['id']).json()
    assert stored['status'] == 'failed' and stored['end_reason'] == 'runtime_lost'
    report = client.get('/api/v1/conversations/' + row['id'] + '/report').json()
    assert report['usage_complete'] is False and report['estimated_model_cost_usd'] is None


def test_healthy_foreign_worker_lease_is_not_stolen(client):
    row = client.post('/api/v1/conversations', json={}).json()
    user = client.get('/api/v1/users/me').json()
    client.portal.call(conversations.claim, client.database, UUID(user['id']), UUID(row['id']))
    client.portal.call(client.app.state.sessions.maintain_once)
    assert client.get('/api/v1/conversations/' + row['id']).json()['status'] == 'connecting'


def test_lease_renewal_and_loss_stop_a_live_runtime(client, monkeypatch):
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        managed = client.app.state.sessions.sessions[initial['session_id']]
        previous = managed.lease_deadline
        client.portal.call(asyncio.sleep, .05)
        client.portal.call(client.app.state.sessions.maintain_once)
        assert managed.lease_deadline > previous

        async def lost(*args):
            return None
        monkeypatch.setattr(repository, 'renew', lost)
        client.portal.call(client.app.state.sessions.maintain_once)
        assert receive_event(ws, 'ended')['report']['end_reason'] == 'lease_lost'


def test_finalization_retries_transient_database_error_idempotently(client, monkeypatch):
    original = repository.finish
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise SQLAlchemyError('PRIVATE_DATABASE_ERROR')
        return await original(*args, **kwargs)
    monkeypatch.setattr(repository, 'finish', flaky)
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        ws.send_json({'type': 'stop'})
        report = receive_event(ws, 'ended')['report']
        assert report['persisted'] is True
    assert len(calls) == 2
    assert client.get('/api/v1/conversations/' + initial['session_id']).json()['status'] == 'ended'


def test_graceful_shutdown_closes_provider_and_persists_terminal_state(client):
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        client.portal.call(client.app.state.sessions.close)
        report = receive_event(ws, 'ended')['report']
        assert report['end_reason'] == 'server_shutdown' and report['persisted']
    assert all(connection.closed for connection in client.app.state.provider.connections)
    assert client.get('/api/v1/conversations/' + initial['session_id']).json()['status'] == 'failed'


def test_silent_transport_closes_provider_then_expires_grace():
    options = settings(session_max_seconds=3, client_reconnect_grace_seconds=.15,
                       client_transport_timeout_seconds=.1)
    with FoundationClient(create_app(options, RecoveryProvider())) as client:
        with client.websocket_connect('/ws/live') as ws:
            initial = start(ws)
            wait_until(client, lambda: client.app.state.provider.connections[0].closed)
        wait_until(client, lambda: not client.app.state.active)
        report = client.get('/api/v1/conversations/' + initial['session_id'] + '/report').json()
        assert report['end_reason'] == 'client_reconnect_timeout'


def test_finalization_outage_is_reported_and_expired_record_is_recovered(client, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise SQLAlchemyError('PRIVATE_DATABASE_MESSAGE')
    monkeypatch.setattr(repository, 'finish', unavailable)
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        ws.send_json({'type': 'stop'})
        report = receive_event(ws, 'ended')['report']
        assert not report['persisted']
        assert 'PRIVATE_DATABASE_MESSAGE' not in json.dumps(report)
    assert not client.app.state.active

    async def expire():
        async with client.database.sessions.begin() as session:
            await session.execute(update(Conversation).where(Conversation.id == UUID(initial['session_id']))
                                  .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        await client.app.state.sessions.maintain_once()
    client.portal.call(expire)
    stored = client.get('/api/v1/conversations/' + initial['session_id']).json()
    assert stored['status'] == 'failed' and stored['end_reason'] == 'runtime_lost'


def test_stop_endpoint_is_owner_scoped_and_can_cancel_unstarted_record(client):
    row = client.post('/api/v1/conversations', json={}).json()
    credentials = {'email': 'other@example.com', 'password': 'OtherPassword123!'}
    client.post('/api/v1/auth/register', json=credentials)
    token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
    path = '/api/v1/conversations/' + row['id'] + '/stop'
    assert client.post(path, headers={'Authorization': f'Bearer {token}'}).status_code == 404
    assert client.post(path).status_code == 204
    assert client.post(path).status_code == 204
    assert client.get('/api/v1/conversations/' + row['id']).json()['status'] == 'ended'


def test_database_outage_cannot_extend_local_lease_deadline(client, monkeypatch):
    async def unavailable(*args):
        raise SQLAlchemyError('temporary_database_outage')
    with client.websocket_connect('/ws/live') as ws:
        initial = start(ws)
        managed = client.app.state.sessions.sessions[initial['session_id']]
        previous = managed.lease_deadline
        monkeypatch.setattr(repository, 'renew', unavailable)
        client.portal.call(client.app.state.sessions.maintain_once)
        assert managed.lease_deadline == previous
        # Advance the local lease clock without sleeping through a real outage.
        async def lose_lease():
            managed.lease_deadline = monotonic() - 1
        client.portal.call(lose_lease)
        assert receive_event(ws, 'ended')['report']['end_reason'] == 'lease_lost'
    assert all(connection.closed for connection in client.app.state.provider.connections)


def test_upgrade_recovers_phase3_active_records_without_restoring_context(client):
    from alembic import command
    from alembic.config import Config
    from app.core.paths import PROJECT_ROOT

    row = client.post('/api/v1/conversations', json={}).json()

    async def upgrade_legacy():
        config = Config(str(PROJECT_ROOT / 'alembic.ini'))

        def migrate(connection):
            config.attributes['connection'] = connection
            command.downgrade(config, '0001_foundation')
            # The update references only columns present in the Phase 3 schema.
            connection.execute(update(Conversation).where(Conversation.id == UUID(row['id'])).values(status='active'))
            command.upgrade(config, 'head')
        async with client.database.engine.begin() as connection:
            await connection.run_sync(migrate)
    client.portal.call(upgrade_legacy)
    stored = client.get('/api/v1/conversations/' + row['id']).json()
    assert stored['status'] == 'failed' and stored['end_reason'] == 'migration_interrupted'
    assert not client.app.state.provider.connections
