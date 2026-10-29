import json
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import Conversation, ConversationMessage
from app.main import create_app
from app.services.continuation import load_context, summarize_one
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeProvider


@pytest.fixture
def client():
    with FoundationClient(create_app(Settings(_env_file=None), FakeProvider())) as value:
        yield value


def seed(client, count=14):
    created = client.post('/api/v1/conversations', json={}).json()
    async def insert():
        async with client.database.sessions.begin() as session:
            row = await session.get(Conversation, UUID(created['id']))
            row.status, row.ended_at, row.message_count = 'ended', utcnow(), count
            for index in range(count):
                now = utcnow()
                session.add(ConversationMessage(id=uuid4(), conversation_id=row.id,
                    sequence=index + 1, role='user' if index % 2 == 0 else 'assistant',
                    text=f'Kotlin message {index}', state='complete', revision=1,
                    created_at=now, updated_at=now, completed_at=now))
            # End timestamp after the final transcript checkpoint.
            row.ended_at = utcnow()
        return row.user_id
    return UUID(created['id']), client.portal.call(insert)


def test_continue_owned_terminal_and_bounded_history(client):
    parent, owner = seed(client)
    response = client.post(f'/api/v1/conversations/{parent}/continue', json={})
    assert response.status_code == 201, response.text
    assert response.json()['continued_from_id'] == str(parent)
    context = client.portal.call(load_context, client.database, owner, parent, 1024)
    assert len(json.dumps(context, ensure_ascii=False).encode()) <= 1024
    assert context['truncated']
    assert client.portal.call(load_context, client.database, uuid4(), parent, 1024)['sessions'] == []
    pending = response.json()['id']
    assert client.post(f'/api/v1/conversations/{pending}/continue', json={}).status_code == 409
    assert client.post(f'/api/v1/conversations/{uuid4()}/continue', json={}).status_code == 404


def test_summary_checkpoint_fallback_and_deletion(client):
    parent, owner = seed(client)
    calls = []
    async def generate(messages):
        calls.append(messages)
        return 'Practised Kotlin. Next explain cancellation.'
    settings = client.app.state.settings
    assert client.portal.call(summarize_one, client.database, settings, generate)
    assert not client.portal.call(summarize_one, client.database, settings, generate)
    context = client.portal.call(load_context, client.database, owner, parent, 12000)
    assert context['sessions'][0]['summary'].startswith('Practised Kotlin')
    assert context['sessions'][0]['messages'] == []
    assert len(calls) == 1
    assert client.delete(f'/api/v1/conversations/{parent}').status_code == 204
    assert client.portal.call(load_context, client.database, owner, parent, 12000)['sessions'] == []


def test_failed_summary_remains_retryable(client):
    seed(client)
    async def fail(messages):
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        client.portal.call(summarize_one, client.database, client.app.state.settings, fail)
    async def succeed(messages):
        return 'Recovered summary'
    assert client.portal.call(summarize_one, client.database, client.app.state.settings, succeed)


def test_transcript_edit_during_generation_rejects_stale_summary(client):
    parent, owner = seed(client)
    async def generate(messages):
        from sqlalchemy import update
        async with client.database.sessions.begin() as session:
            await session.execute(update(ConversationMessage).where(
                ConversationMessage.conversation_id == parent, ConversationMessage.sequence == 1,
            ).values(text='Corrected fact', revision=2, updated_at=utcnow()))
        return 'Stale summary'
    assert not client.portal.call(summarize_one, client.database, client.app.state.settings, generate)
    context = client.portal.call(load_context, client.database, owner, parent, 12000)
    assert context['sessions'][0]['summary'] == ''
    assert context['sessions'][0]['messages'][0]['text'] == 'Corrected fact'


def test_profile_pronouns_are_in_new_snapshot(client):
    response = client.patch('/api/v1/users/me/preferences', json={'display_name': 'Dhiraj', 'pronouns': 'he/him'})
    assert response.status_code == 200
    row = client.post('/api/v1/conversations', json={}).json()
    assert row['preferences_snapshot']['pronouns'] == 'he/him'


def test_two_users_can_run_with_configured_capacity():
    from tests.helpers.fakes import settings
    with FoundationClient(create_app(settings(max_active_sessions=2), FakeProvider())) as client:
        first = client.post('/api/v1/conversations', json={}).json()['id']
        credentials = {'email': 'second@example.com', 'password': 'Test123!'}
        assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
        token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
        headers = {'authorization': f'Bearer {token}'}
        second = client.post('/api/v1/conversations', json={}, headers=headers).json()['id']
        with client.websocket_connect('/ws/live') as one:
            one.send_json({'type': 'start', 'conversation_id': first})
            assert one.receive_json()['type'] == 'ready'
            with client.websocket_connect('/ws/live', headers=headers) as two:
                two.send_json({'type': 'start', 'conversation_id': second})
                event = two.receive_json()
                assert event['type'] == 'ready', event
                assert len(client.app.state.sessions.sessions) == 2
                two.send_json({'type': 'stop'})
                assert two.receive_json()['type'] == 'ended'
            one.send_json({'type': 'stop'})
            assert one.receive_json()['type'] == 'ended'
