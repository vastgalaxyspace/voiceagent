import asyncio
import json
import os
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.core.errors import AppError
from app.db.models import Conversation, User, UserPreferences
from app.main import create_app
from app.schemas.memory import MemoryCreate
from app.services import memories
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeProvider, settings

ROOT = '/api/v1/users/me/memories'
PREFERENCES = '/api/v1/users/me/preferences'


@pytest.fixture
def client():
    with FoundationClient(create_app(settings(), FakeProvider())) as value:
        yield value


def enable(client):
    assert client.patch(PREFERENCES, json={'memory_enabled': True}).status_code == 200


def remember(client, key='background', content='I am learning Kotlin.', priority=50):
    result = client.post(ROOT, json={'key': key, 'content': content, 'priority': priority})
    assert result.status_code == 201, result.text
    return result.json()


def conversation(client):
    result = client.post('/api/v1/conversations', json={})
    assert result.status_code == 201, result.text
    return result.json()


def begin(socket, row):
    socket.send_json({'type': 'start', 'conversation_id': row['id']})
    assert socket.receive_json()['type'] == 'ready'


def test_memory_requires_opt_in_and_has_versioned_edits_and_forget(client):
    assert client.get(ROOT).json()['memory_enabled'] is False
    assert client.post(ROOT, json={'key': 'background', 'content': 'Kotlin'}).status_code == 409
    enable(client)
    row = remember(client)
    assert row['version'] == 1
    assert client.post(ROOT, json={'key': row['key'], 'content': 'duplicate'}).json()['error'] == 'memory_key_exists'
    edited = client.put(ROOT + '/' + row['id'], json={
        'content': 'I am practising interviews.', 'priority': 80, 'expected_version': 1,
    })
    assert edited.status_code == 200
    assert edited.json()['version'] == 2
    stale = client.put(ROOT + '/' + row['id'], json={'content': 'stale', 'expected_version': 1})
    assert stale.status_code == 409 and stale.json()['error'] == 'memory_version_conflict'
    client.patch(PREFERENCES, json={'memory_enabled': False})
    assert len(client.get(ROOT).json()['items']) == 1  # Disabling is not deletion.
    assert client.delete(ROOT + '/' + row['id']).status_code == 204
    assert client.get(ROOT).json()['items'] == []
    assert client.delete(ROOT).status_code == 204
    assert client.delete(ROOT).status_code == 204


def test_memory_is_private_and_foreign_ids_match_missing_ids(client):
    enable(client)
    row = remember(client, content='PRIVATE_MEMORY_TEXT')
    credentials = {'email': 'second@example.com', 'password': 'SecondPassword123!'}
    assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
    token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get(ROOT, headers=headers).json()['items'] == []
    assert client.get(ROOT + '/' + row['id'], headers=headers).status_code == 404
    assert client.get(ROOT + '/' + row['id']).json()['content'] == 'PRIVATE_MEMORY_TEXT'
    assert client.delete(ROOT + '/' + row['id'], headers=headers).json() == {'error': 'memory_not_found'}
    assert client.put(ROOT + '/' + row['id'], headers=headers,
                      json={'content': 'overwrite', 'expected_version': 1}).status_code == 404
    assert client.get(ROOT).json()['items'][0]['content'] == 'PRIVATE_MEMORY_TEXT'


@pytest.mark.parametrize('payload', [
    {'key': 'bad key', 'content': 'text'}, {'key': 'ok', 'content': ' '},
    {'key': 'ok', 'content': 'x' * 501}, {'key': 'ok', 'content': 'text', 'priority': 101},
    {'key': 'ok', 'content': 'text', 'user_id': 'foreign'},
    {'key': 'ok', 'content': 'invalid\x00text'},
])
def test_memory_validation_rejects_unbounded_or_authority_fields(client, payload):
    enable(client)
    assert client.post(ROOT, json=payload).status_code == 422
    assert client.get(ROOT).json()['items'] == []


def test_personalization_is_snapshotted_and_memory_text_is_not_duplicated(client):
    enable(client)
    client.patch(PREFERENCES, json={'display_name': 'Asha', 'custom_instructions': 'Use practical examples.',
                                  'conversation_mode': 'interview_practice'})
    remember(client, content='PRIVATE_FACT_KOTLIN')
    row = conversation(client)
    assert 'PRIVATE_FACT_KOTLIN' not in json.dumps(row)
    assert len(row['preferences_snapshot']['memory_context']['items']) == 1
    client.patch(PREFERENCES, json={'display_name': 'New name', 'custom_instructions': 'Different style.'})
    with client.websocket_connect('/ws/live') as socket:
        begin(socket, row)
        prompt = client.app.state.provider.last_prompt
        assert 'Asha' in prompt and 'Use practical examples.' in prompt
        assert 'New name' not in prompt and 'Different style.' not in prompt
        assert 'PRIVATE_FACT_KOTLIN' in prompt
        assert 'Do not invent' in prompt and 'lower-trust' in prompt
        socket.send_json({'type': 'stop'})
        report = socket.receive_json()['report']
    assert report['memory_item_count'] == 1
    assert 'PRIVATE_FACT_KOTLIN' not in json.dumps(report)
    assert 'PRIVATE_FACT_KOTLIN' not in client.get('/api/v1/conversations/' + row['id']).text


@pytest.mark.parametrize('change', ['edit', 'delete', 'disable'])
def test_changed_memory_invalidates_pending_admission_without_reserving_allowance(client, change):
    enable(client)
    memory = remember(client)
    row = conversation(client)
    if change == 'edit':
        client.put(ROOT + '/' + memory['id'], json={'content': 'Changed', 'expected_version': 1})
    elif change == 'delete':
        client.delete(ROOT + '/' + memory['id'])
    else:
        client.patch(PREFERENCES, json={'memory_enabled': False})
    with client.websocket_connect('/ws/live') as socket:
        socket.send_json({'type': 'start', 'conversation_id': row['id']})
        assert socket.receive_json()['code'] == 'conversation_memory_changed'
    assert not client.app.state.provider.opened
    assert client.get('/api/v1/usage/me').json()['sessions_started'] == 0
    assert client.get('/api/v1/conversations/' + row['id']).json()['status'] == 'created'


@pytest.mark.parametrize('change', ['delete', 'disable', 'clear'])
def test_forget_or_disable_stops_live_memory_session_and_settles(client, change):
    enable(client)
    memory = remember(client)
    row = conversation(client)
    with client.websocket_connect('/ws/live') as socket:
        begin(socket, row)
        if change == 'delete':
            assert client.delete(ROOT + '/' + memory['id']).status_code == 204
        elif change == 'clear':
            assert client.delete(ROOT).status_code == 204
        else:
            assert client.patch(PREFERENCES, json={'memory_enabled': False}).status_code == 200
        report = socket.receive_json()['report']
    assert report['end_reason'] == 'memory_changed'
    assert report['persisted'] is True
    assert client.app.state.provider.closed
    assert client.get('/api/v1/usage/me').json()['reserved_seconds'] == 0


def test_heartbeat_detects_memory_change_from_another_process(client):
    enable(client)
    remember(client)
    row = conversation(client)
    with client.websocket_connect('/ws/live') as socket:
        begin(socket, row)

        async def external_change():
            async with client.database.sessions.begin() as session:
                await session.execute(update(UserPreferences).values(memory_revision=UserPreferences.memory_revision + 1))
            await client.app.state.sessions.maintain_once()
        client.portal.call(external_change)
        assert socket.receive_json()['report']['end_reason'] == 'memory_changed'


def test_memory_quota_and_prompt_selection_are_bounded():
    options = settings(memory_max_items=3, memory_prompt_max_items=2, memory_prompt_max_bytes=128)
    with FoundationClient(create_app(options, FakeProvider())) as client:
        enable(client)
        remember(client, 'oversized', 'ह' * 100, 100)
        remember(client, 'preferred', 'Use short examples.', 80)
        remember(client, 'other', 'Learning Kotlin.', 30)
        assert client.post(ROOT, json={'key': 'extra', 'content': 'extra'}).json()['error'] == 'memory_limit_reached'
        row = conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            begin(socket, row)
            data = json.loads(client.app.state.provider.last_prompt.split('USER_CONTEXT_JSON=', 1)[1])
            facts = data['saved_memories']
            assert len(facts) == 2
            assert facts[0]['key'] == 'preferred'
            assert len(json.dumps(facts, ensure_ascii=False, separators=(',', ':')).encode()) <= 128
            socket.send_json({'type': 'stop'})
            assert socket.receive_json()['report']['memory_item_count'] == 2


def test_legacy_conversation_snapshot_still_uses_legacy_prompt(client):
    from app.services.conversations import fingerprint
    from app.db.models import PromptVersion
    row = conversation(client)

    async def legacy():
        async with client.database.sessions.begin() as session:
            stored = await session.get(Conversation, UUID(row['id']))
            prompt = await session.get(PromptVersion, stored.prompt_version)
            snapshot = {key: stored.preferences_snapshot[key] for key in ('language', 'goal', 'response_detail')}
            stored.preferences_snapshot = snapshot
            stored.configuration_fingerprint = fingerprint(prompt.instructions, prompt.version, snapshot,
                                                          stored.configuration_snapshot)
    client.portal.call(legacy)
    with client.websocket_connect('/ws/live') as socket:
        begin(socket, row)
        assert 'USER_CONTEXT_JSON=' not in client.app.state.provider.last_prompt
        socket.send_json({'type': 'stop'})
        assert socket.receive_json()['report']['memory_item_count'] == 0


def test_reduced_memory_prompt_budget_rejects_pending_conversation(client):
    enable(client)
    remember(client, content='x' * 300)
    row = conversation(client)
    client.app.state.settings.memory_prompt_max_bytes = 128
    with client.websocket_connect('/ws/live') as socket:
        socket.send_json({'type': 'start', 'conversation_id': row['id']})
        assert socket.receive_json()['code'] == 'conversation_memory_budget_changed'
    assert not client.app.state.provider.opened


def test_memory_disable_prevents_detached_client_from_resuming():
    from tests.helpers.recovery_provider import RecoveryProvider
    provider = RecoveryProvider()
    with FoundationClient(create_app(settings(client_reconnect_grace_seconds=1), provider)) as client:
        enable(client)
        remember(client)
        row = conversation(client)
        with client.websocket_connect('/ws/live') as socket:
            begin(socket, row)

            async def checkpoint():
                async with asyncio.timeout(2):
                    while not client.app.state.sessions.sessions[row['id']].relay._resume_handle:
                        await asyncio.sleep(.01)
            client.portal.call(checkpoint)
        assert client.patch(PREFERENCES, json={'memory_enabled': False}).status_code == 200
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': row['id']})
            assert socket.receive_json()['type'] == 'error'

        async def finished():
            async with asyncio.timeout(2):
                while row['id'] in client.app.state.sessions.sessions:
                    await asyncio.sleep(.01)
        client.portal.call(finished)
        assert client.get('/api/v1/conversations/' + row['id'] + '/report').json()['end_reason'] == 'memory_changed'
        assert len(provider.handles) == 1


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Row-lock quota race requires PostgreSQL')
def test_parallel_memory_creation_cannot_exceed_quota():
    with FoundationClient(create_app(settings(memory_max_items=1), FakeProvider())) as client:
        enable(client)

        async def race():
            async with client.database.sessions() as session:
                user = await session.scalar(select(User).where(User.email == 'default@example.com'))

            async def create(key):
                try:
                    await memories.create(client.database, client.app.state.settings, user.id,
                                          MemoryCreate(key=key, content='Remember this'))
                    return 'accepted'
                except AppError as exc:
                    return exc.code
            return await asyncio.gather(create('one'), create('two'))
        assert sorted(client.portal.call(race)) == ['accepted', 'memory_limit_reached']
