import asyncio
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from google.genai import types
from sqlalchemy import update

from app.db.models import User, UserPreferences
from app.main import create_app
from app.services.live_tools import ToolSession
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeConnection, FakeProvider, settings

ROOT = '/api/v1/knowledge/entries'
ADMIN = '/api/v1/admin/knowledge'


class ToolProvider:
    @asynccontextmanager
    async def connect(self, prompt, *, resume_handle=None):
        self.prompt = prompt
        self.connection = FakeConnection()
        self.responses = asyncio.Queue()

        async def respond(responses):
            await self.responses.put(responses[0])
        self.connection.send_tool_responses = respond
        yield self.connection


@pytest.fixture
def client():
    with FoundationClient(create_app(settings(live_tools_enabled=True), ToolProvider())) as value:
        yield value


def entry(client, title='Kotlin', content='PRIVATE_KNOWLEDGE coroutine reference', **extra):
    result = client.post(ROOT, json={'title': title, 'content': content, **extra})
    assert result.status_code == 201, result.text
    return result.json()


def second_user(client):
    credentials = {'email': 'other@example.com', 'password': 'OtherPassword123!'}
    assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
    token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
    return {'Authorization': 'Bearer ' + token}


def promote(client):
    async def run():
        async with client.database.sessions.begin() as session:
            await session.execute(update(User).where(User.email == 'default@example.com').values(is_admin=True))
    client.portal.call(run)


def start(client, socket, use_tools=True):
    result = client.post('/api/v1/conversations', json={'use_tools': use_tools})
    assert result.status_code == 201, result.text
    socket.send_json({'type': 'start', 'conversation_id': result.json()['id']})
    ready = socket.receive_json()
    assert ready['type'] == 'ready', ready
    assert bool(ready['tools']) is use_tools
    return result.json()


def send_call(client, name, args=None, identifier='call-1'):
    message = types.LiveServerMessage(tool_call=types.LiveServerToolCall(function_calls=[
        types.FunctionCall(id=identifier, name=name, args=args or {}),
    ]))
    client.portal.call(client.app.state.provider.connection.queue.put, message)


def result(client):
    async def get():
        async with asyncio.timeout(4):
            return await client.app.state.provider.responses.get()
    return client.portal.call(get)


def stop(socket):
    socket.send_json({'type': 'stop'})
    while True:
        event = socket.receive()
        if event.get('text'):
            value = json.loads(event['text'])
            if value['type'] == 'ended':
                return value['report']


def test_private_ownership_versions_and_pagination(client):
    row = entry(client)
    other = second_user(client)
    assert client.get(ROOT, headers=other).json()['items'] == []
    assert client.get(ROOT + '/' + row['id'], headers=other).status_code == 404
    assert client.delete(ROOT + '/' + row['id'], headers=other).status_code == 404
    assert client.get('/api/v1/knowledge/search', params={'q': 'coroutine'}, headers=other).json()['items'] == []
    listed = client.get(ROOT).json()['items'][0]
    assert 'content' not in listed
    changed = client.put(ROOT + '/' + row['id'], json={'title': 'Updated', 'content': 'New text', 'expected_version': 1})
    assert changed.status_code == 200 and changed.json()['version'] == 2
    assert client.put(ROOT + '/' + row['id'], json={'title': 'Stale', 'content': 'old', 'expected_version': 1}).status_code == 409
    entry(client)
    assert client.get(ROOT, params={'limit': 1}).json()['next_offset'] == 1
    assert client.delete(ROOT + '/' + row['id']).status_code == 204
    assert client.get(ROOT + '/' + row['id']).status_code == 404


def test_shared_drafts_and_admin_permissions(client):
    assert client.post(ADMIN, json={'title': 'Manual', 'content': 'shared reference'}).status_code == 403
    promote(client)
    row = client.post(ADMIN, json={'title': 'Manual', 'content': 'shared reference'}).json()
    other = second_user(client)
    assert client.get(ROOT + '/' + row['id'], headers=other).status_code == 404
    assert client.get(ADMIN + '/' + row['id']).json()['content'] == 'shared reference'
    assert client.get(ADMIN, headers=other).status_code == 403
    published = client.put(ADMIN + '/' + row['id'], json={
        'title': 'Manual', 'content': 'shared reference', 'published': True, 'expected_version': 1})
    assert published.status_code == 200
    assert client.get(ROOT + '/' + row['id'], headers=other).status_code == 200
    assert client.get('/api/v1/knowledge/search', params={'q': 'shared'}, headers=other).json()['items']
    assert client.put(ROOT + '/' + row['id'], json={'title': 'Hijack', 'content': 'bad', 'expected_version': 2}).status_code == 404
    assert client.delete(ADMIN + '/' + row['id']).status_code == 204


@pytest.mark.parametrize('payload', [
    {'title': ' ', 'content': 'text'}, {'title': 'x', 'content': 'bad\x00text'},
    {'title': 'x', 'content': 'x' * 6001}, {'title': 'x', 'content': 'text', 'owner_id': str(uuid4())},
    {'title': 'x', 'content': 'text', 'source_url': 'javascript:alert(1)'},
    {'title': 'x', 'content': 'text', 'published': True},
])
def test_knowledge_rejects_invalid_data(client, payload):
    assert client.post(ROOT, json=payload).status_code == 422


def test_search_query_bounds_multilingual_and_quota(client):
    entry(client, title='नमस्ते', content='नमस्ते दुनिया')
    assert client.get('/api/v1/knowledge/search', params={'q': 'नमस्ते'}).json()['items']
    assert client.get('/api/v1/knowledge/search', params={'q': ' '}).status_code == 422
    assert client.get('/api/v1/knowledge/search', params={'q': 'a b c d e f g h i'}).status_code == 422
    assert client.get('/api/v1/knowledge/search', params={'q': '%_'}).json()['items'] == []
    client.app.state.settings.knowledge_max_private_entries = 1
    assert client.post(ROOT, json={'title': 'Full', 'content': 'Full'}).status_code == 409


def test_tools_require_both_switches_and_snapshot_has_no_knowledge_text(client):
    entry(client)
    row = client.post('/api/v1/conversations', json={'use_tools': True}).json()
    assert row['configuration_snapshot']['live_tools_enabled'] is True
    assert 'knowledge_context' in row['preferences_snapshot']
    assert 'PRIVATE_KNOWLEDGE' not in json.dumps(row)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket, use_tools=False)
        assert 'Available tools are read-only' not in client.app.state.provider.prompt
        stop(socket)
    client.app.state.settings.live_tools_enabled = False
    assert client.post('/api/v1/conversations', json={'use_tools': True}).json()['error'] == 'tools_disabled'


def test_pending_conversation_rejects_changed_knowledge(client):
    row = client.post('/api/v1/conversations', json={'use_tools': True}).json()
    entry(client)
    with client.websocket_connect('/ws/live') as socket:
        socket.send_json({'type': 'start', 'conversation_id': row['id']})
        assert socket.receive_json()['code'] == 'conversation_knowledge_changed'
    assert client.get('/api/v1/usage/me').json()['reserved_seconds'] == 0


def test_search_read_and_usage_tools_with_source_events_and_private_reports(client):
    row = entry(client)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        assert 'untrusted reference data' in client.app.state.provider.prompt
        send_call(client, 'search_knowledge', {'query': 'PRIVATE_KNOWLEDGE'})
        response = result(client)
        assert response['id'] == 'call-1' and response['response']['ok']
        assert response['response']['items'][0]['id'] == row['id']
        event = socket.receive_json()
        assert event['type'] == 'knowledge_sources' and 'excerpt' not in event['sources'][0]
        send_call(client, 'get_knowledge_entry', {'entry_id': row['id'], 'expected_version': 1}, 'read')
        assert result(client)['response']['excerpt'].startswith('PRIVATE_KNOWLEDGE')
        assert socket.receive_json()['type'] == 'knowledge_sources'
        send_call(client, 'get_usage_allowance', identifier='usage')
        assert result(client)['response']['remaining_session_seconds'] > 0
        report = stop(socket)
    assert report['tool_call_count'] == 3 and report['knowledge_result_count'] == 2
    assert 'PRIVATE_KNOWLEDGE' not in json.dumps(report)
    assert 'call-1' not in json.dumps(report)


@pytest.mark.parametrize('name,args,code', [
    ('delete_knowledge', {}, 'tool_not_allowed'),
    ('get_usage_allowance', {'user_id': str(uuid4())}, 'invalid_tool_arguments'),
    ('search_knowledge', {'query': 'x', 'limit': '3'}, 'invalid_tool_arguments'),
    ('get_knowledge_entry', {'entry_id': str(uuid4()), 'expected_version': 1}, 'knowledge_not_found'),
])
def test_untrusted_tool_calls_cannot_expand_authority(client, name, args, code):
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, name, args)
        assert result(client)['response'] == {'ok': False, 'error': code}
        assert stop(socket)['tool_error_count'] == 1


def test_tool_limit_and_reused_ids(client):
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_usage_allowance')
        assert result(client)['response']['ok']
        send_call(client, 'search_knowledge', {'query': 'changed'})
        assert socket.receive_json()['report']['end_reason'] == 'invalid_tool_call'


def test_inflight_cancel_keeps_audio_duplex_and_does_not_send_result(client, monkeypatch):
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(self, call):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(ToolSession, 'execute', blocked)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_usage_allowance')
        client.portal.call(asyncio.wait_for, entered.wait(), 3)
        socket.send_bytes(b'\0\0' * 800)
        assert socket.receive_bytes()
        assert socket.receive_json()['type'] == 'turn_complete'
        client.portal.call(client.app.state.provider.connection.queue.put, types.LiveServerMessage(
            tool_call_cancellation=types.LiveServerToolCallCancellation(ids=['call-1'])))
        client.portal.call(asyncio.wait_for, cancelled.wait(), 3)
        report = stop(socket)
        assert client.app.state.provider.responses.empty()
    assert report['tool_cancelled_count'] == 1


def test_tool_timeout_returns_safe_error(client, monkeypatch):
    client.app.state.settings.tool_timeout_seconds = .1

    async def blocked(self, call):
        await asyncio.Event().wait()
    monkeypatch.setattr(ToolSession, 'execute', blocked)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_usage_allowance')
        assert result(client)['response']['error'] == 'tool_timeout'
        stop(socket)


def test_cached_duplicate_not_reexecuted_and_knowledge_edits_end_session(client, monkeypatch):
    calls = []
    original = ToolSession.execute

    async def track(self, call):
        calls.append(call.id)
        return await original(self, call)
    monkeypatch.setattr(ToolSession, 'execute', track)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_usage_allowance')
        first = result(client)
        send_call(client, 'get_usage_allowance')
        assert result(client) == first
        assert calls == ['call-1']
        entry(client)
        assert socket.receive_json()['report']['end_reason'] == 'knowledge_changed'


def test_lookup_rechecks_knowledge_revision_before_sending_data(client, monkeypatch):
    entry(client)
    original = ToolSession.execute

    async def change_after_read(self, call):
        response = await original(self, call)
        async with self.database.sessions.begin() as session:
            await session.execute(update(UserPreferences).where(UserPreferences.user_id == self.principal.user.id)
                                  .values(knowledge_revision=UserPreferences.knowledge_revision + 1))
        return response
    monkeypatch.setattr(ToolSession, 'execute', change_after_read)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'search_knowledge', {'query': 'coroutine'})
        assert socket.receive_json()['report']['end_reason'] == 'knowledge_changed'
        assert client.app.state.provider.responses.empty()


def test_foreign_tool_lookup_and_unicode_result_budget(client):
    row = entry(client, content='अ' * 2000)
    other = second_user(client)
    foreign = client.post(ROOT, headers=other, json={'title': 'Secret', 'content': 'OTHER_PRIVATE_TEXT'}).json()
    client.app.state.settings.tool_result_max_bytes = 1024
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_knowledge_entry', {'entry_id': foreign['id'], 'expected_version': 1}, 'foreign')
        assert result(client)['response']['error'] == 'knowledge_not_found'
        send_call(client, 'get_knowledge_entry', {'entry_id': row['id'], 'expected_version': 1, 'max_chars': 1000}, 'unicode')
        response = result(client)['response']
        assert response['ok'] and response['next_offset'] < 1000
        assert len(json.dumps(response, ensure_ascii=False, separators=(',', ':')).encode()) <= 1024
        assert socket.receive_json()['type'] == 'knowledge_sources'
        stop(socket)


def test_call_cap_applies_across_responses(client):
    client.app.state.settings.tool_max_calls = 1
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        send_call(client, 'get_usage_allowance', identifier='first')
        assert result(client)['response']['ok']
        send_call(client, 'get_usage_allowance', identifier='second')
        assert socket.receive_json()['report']['end_reason'] == 'tool_limit'


def test_other_private_knowledge_does_not_invalidate_current_session(client):
    other = second_user(client)
    with client.websocket_connect('/ws/live') as socket:
        start(client, socket)
        assert client.post(ROOT, headers=other, json={'title': 'Other', 'content': 'Private'}).status_code == 201
        send_call(client, 'get_usage_allowance')
        assert result(client)['response']['ok']
        assert stop(socket)['end_reason'] == 'user_stopped'


def test_knowledge_quota_is_serialized(client):
    from app.core.errors import AppError
    from app.schemas.knowledge import KnowledgeCreate
    from app.services import auth, knowledge
    client.app.state.settings.knowledge_max_private_entries = 1

    async def race():
        principal = await auth.authenticate(client.database, client.token)
        body = KnowledgeCreate(title='Concurrent', content='reference')
        values = await asyncio.gather(*[
            knowledge.create(client.database, client.app.state.settings, principal, body) for _ in range(3)
        ], return_exceptions=True)
        assert sum(not isinstance(value, BaseException) for value in values) == 1
        assert all(not isinstance(value, BaseException) or isinstance(value, AppError)
                   and value.code == 'knowledge_limit_reached' for value in values)
    client.portal.call(race)
    assert len(client.get(ROOT).json()['items']) == 1
