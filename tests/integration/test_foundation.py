import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.core.passwords import token_digest
from app.db.base import Base, utcnow
from app.db.models import AuthSession, Conversation, PromptVersion, User
from app.db.session import Database
from app.main import create_app
from app.services import conversations
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeProvider, settings


@pytest.fixture
def client():
    with FoundationClient(create_app(settings(), FakeProvider())) as value:
        yield value


def second_user(client):
    credentials = {'email': 'second@example.com', 'password': 'SecondPassword123!'}
    assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
    response = client.post('/api/v1/auth/login', json=credentials)
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def new_conversation(client, **kwargs):
    response = client.post('/api/v1/conversations', json=kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_login_and_password_hashing(client):
    credentials = {'email': 'Alice@EXAMPLE.COM', 'password': 'LongPasswordForAlice!'}
    created = client.post('/api/v1/auth/register', json=credentials)
    assert created.status_code == 201
    assert created.json()['email'] == 'alice@example.com'
    assert 'password' not in created.text
    assert client.post('/api/v1/auth/register', json=credentials).status_code == 409
    logged_in = client.post('/api/v1/auth/login', json=credentials)
    assert logged_in.status_code == 200
    token = logged_in.json()['access_token']
    assert client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {token}'}).json()['email'] == 'alice@example.com'

    async def inspect():
        async with client.database.sessions() as session:
            user = await session.scalar(select(User).where(User.email == 'alice@example.com'))
            auth = await session.get(AuthSession, token_digest(token))
            assert user.password_hash.startswith('$argon2id$')
            assert user.password_hash != credentials['password']
            assert auth.token_hash != token
            assert auth.expires_at.tzinfo is not None
    client.portal.call(inspect)


def test_invalid_and_unknown_credentials_return_same_safe_error(client):
    for email in ['default@example.com', 'missing@example.com']:
        response = client.post('/api/v1/auth/login', json={'email': email, 'password': 'WrongPassword123!'})
        assert response.status_code == 401
        assert response.json() == {'error': 'invalid_credentials'}
        assert response.headers['www-authenticate'] == 'Bearer'


def test_validation_never_echoes_passwords_or_unexpected_fields(client):
    response = client.post('/api/v1/auth/register', json={
        'email': 'not-an-email', 'password': 'SECRET', 'admin': True,
    })
    assert response.status_code == 422
    assert 'SECRET' not in response.text
    assert '"input"' not in response.text
    assert all('input' not in error for error in response.json()['details'])


def test_missing_and_invalid_bearer_are_rejected(client):
    client.headers.pop('Authorization')
    assert client.get('/api/v1/users/me').status_code == 401
    assert client.get('/api/v1/conversations').status_code == 401
    assert client.get('/api/v1/users/me', headers={'Authorization': 'Bearer invalid'}).status_code == 401


def test_expired_and_disabled_accounts_cannot_authenticate(client):
    async def expire():
        async with client.database.sessions.begin() as session:
            await session.execute(update(AuthSession).where(AuthSession.token_hash == token_digest(client.token))
                                  .values(expires_at=utcnow() - timedelta(seconds=1)))
    client.portal.call(expire)
    assert client.get('/api/v1/users/me').status_code == 401
    token = client.post('/api/v1/auth/login', json={
        'email': 'default@example.com', 'password': 'TestPassword123!',
    }).json()['access_token']

    async def disable():
        async with client.database.sessions.begin() as session:
            await session.execute(update(User).where(User.email == 'default@example.com').values(is_active=False))
    client.portal.call(disable)
    assert client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_logout_revokes_current_session_only(client):
    extra = client.post('/api/v1/auth/login', json={
        'email': 'default@example.com', 'password': 'TestPassword123!',
    }).json()['access_token']
    assert client.post('/api/v1/auth/logout').status_code == 204
    assert client.get('/api/v1/users/me').status_code == 401
    assert client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {extra}'}).status_code == 200


def test_preferences_are_private_validated_and_persistent(client):
    original = client.get('/api/v1/users/me/preferences').json()
    assert original['language'] == 'English and Hindi'
    assert client.patch('/api/v1/users/me/preferences', json={
        'language': 'Hindi', 'response_detail': 'detailed', 'goal': 'Practise interview answers',
    }).status_code == 200
    assert client.get('/api/v1/users/me/preferences').json()['language'] == 'Hindi'
    other = second_user(client)
    assert client.get('/api/v1/users/me/preferences', headers=other).json()['goal'] == ''
    assert client.patch('/api/v1/users/me/preferences', json={'user_id': str(uuid4())}).status_code == 422
    assert client.patch('/api/v1/users/me/preferences', json={'goal': 'a' * 501}).status_code == 422


def test_conversation_ownership_for_read_list_report_and_websocket(client):
    conversation = new_conversation(client)
    other = second_user(client)
    assert client.get('/api/v1/conversations', headers=other).json()['items'] == []
    for suffix in ['', '/report']:
        response = client.get(f'/api/v1/conversations/{conversation["id"]}{suffix}', headers=other)
        assert response.status_code == 404
        assert response.json() == {'error': 'conversation_not_found'}
    with client.websocket_connect('/ws/live', headers={'authorization': other['Authorization']}) as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['code'] == 'conversation_not_found'
    assert not client.app.state.provider.opened


def test_snapshot_stays_fixed_when_preferences_change(client):
    client.patch('/api/v1/users/me/preferences', json={'language': 'Hindi', 'goal': 'Original goal'})
    conversation = new_conversation(client)
    client.patch('/api/v1/users/me/preferences', json={'language': 'English', 'goal': 'New goal'})
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['type'] == 'ready'
        assert 'Original goal' in client.app.state.provider.last_prompt
        assert 'New goal' not in client.app.state.provider.last_prompt
        ws.send_json({'type': 'stop'})
        report = ws.receive_json()['report']
        assert report['session_id'] == conversation['id']
        assert report['persisted'] is True
    stored = client.get(f'/api/v1/conversations/{conversation["id"]}').json()
    assert stored['status'] == 'ended'
    assert stored['ended_at'] is not None
    assert stored['preferences_snapshot']['goal'] == 'Original goal'
    assert client.get(f'/api/v1/conversations/{conversation["id"]}/report').json()['end_reason'] == 'user_stopped'
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['code'] == 'conversation_already_started'


def test_browser_first_frame_auth_and_logout_stops_active_session(client):
    conversation = new_conversation(client)
    with client.websocket_connect('/ws/live', headers={'authorization': ''}) as ws:
        # Omit the HTTP header so the browser's first-frame token is exercised.
        ws.send_json({'type': 'start', 'conversation_id': conversation['id'], 'access_token': client.token})
        assert ws.receive_json()['type'] == 'ready'
        assert client.post('/api/v1/auth/logout').status_code == 204
        assert ws.receive_json()['report']['end_reason'] == 'auth_revoked'


def test_missing_websocket_auth_cannot_open_provider(client):
    conversation = new_conversation(client)
    with client.websocket_connect('/ws/live', headers={'authorization': ''}) as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['code'] == 'authentication_required'
    assert not client.app.state.provider.opened


def test_pagination_is_bounded_and_owner_scoped(client):
    for _ in range(3):
        new_conversation(client)
    first = client.get('/api/v1/conversations?limit=2').json()
    assert len(first['items']) == 2
    assert first['next_offset'] == 2
    second = client.get('/api/v1/conversations?limit=2&offset=2').json()
    assert len(second['items']) == 1
    assert second['next_offset'] is None
    assert client.get('/api/v1/conversations?limit=10000').status_code == 422


def test_prompt_seed_and_migration_match_models(client):
    async def inspect():
        async with client.database.engine.connect() as connection:
            differences = await connection.run_sync(lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata))
            assert differences == []
        async with client.database.sessions() as session:
            prompt = await session.get(PromptVersion, 'phase2-v1')
            assert prompt is not None
            assert prompt.instructions
    client.portal.call(inspect)
    assert client.get('/health/ready').status_code == 200


def test_atomic_claim_allows_only_one_active_conversation_per_user(client):
    first, second = new_conversation(client), new_conversation(client)
    user_id = client.get('/api/v1/users/me').json()['id']

    async def claim_both():
        from uuid import UUID
        results = await asyncio.gather(*[
            conversations.claim(client.database, UUID(user_id), UUID(row['id']))
            for row in [first, second]
        ], return_exceptions=True)
        assert sum(not isinstance(result, Exception) for result in results) == 1
        failures = [result for result in results if isinstance(result, AppError)]
        assert len(failures) == 1 and failures[0].status_code == 409
    client.portal.call(claim_both)


def test_records_and_auth_survive_application_recreation(client):
    conversation = new_conversation(client)
    client.portal.call(client.database.engine.dispose)
    connect_args = {'server_settings': {'search_path': client.schema}} if client.schema else {}
    independent_database = Database(client.app.state.settings, connect_args=connect_args)
    app = create_app(client.app.state.settings, FakeProvider(), independent_database)
    with TestClient(app) as restarted:
        response = restarted.get('/api/v1/conversations/' + conversation['id'],
                                 headers={'Authorization': f'Bearer {client.token}'})
        assert response.status_code == 200
        assert response.json()['id'] == conversation['id']


def test_no_database_fails_closed_without_exposing_configuration():
    with TestClient(create_app(settings(), FakeProvider())) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/health/ready').status_code == 503
        assert client.post('/api/v1/auth/register', json={
            'email': 'new@example.com', 'password': 'NewPassword123!',
        }).json() == {'error': 'database_not_configured'}


def test_prompt_versions_are_immutable_and_new_selection_affects_only_new_conversations(client):
    from app.services.prompts import publish
    original = new_conversation(client)
    client.portal.call(publish, client.database, 'voice-v2', 'CUSTOM SYSTEM INSTRUCTIONS')
    with pytest.raises(AppError) as exc:
        client.portal.call(publish, client.database, 'voice-v2', 'OVERWRITTEN INSTRUCTIONS')
    assert exc.value.code == 'prompt_version_already_exists'
    client.app.state.settings.active_prompt_version = 'voice-v2'
    updated = new_conversation(client)
    assert original['prompt_version'] == 'phase2-v1'
    assert updated['prompt_version'] == 'voice-v2'
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json({'type': 'start', 'conversation_id': updated['id']})
        assert ws.receive_json()['type'] == 'ready'
        assert 'CUSTOM SYSTEM INSTRUCTIONS' in client.app.state.provider.last_prompt
        assert 'OVERWRITTEN' not in client.app.state.provider.last_prompt
        ws.send_json({'type': 'stop'})
        assert ws.receive_json()['report']['prompt_version'] == 'voice-v2'


def test_provider_setup_failure_is_durable(client):
    client.app.state.provider.fail = True
    conversation = new_conversation(client)
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['report']['end_reason'] == 'provider_error'
    stored = client.get('/api/v1/conversations/' + conversation['id']).json()
    assert stored['status'] == 'failed'
    assert stored['end_reason'] == 'provider_error'


def test_access_token_expiration_ends_live_session(client):
    conversation = new_conversation(client)

    async def expire_soon():
        async with client.database.sessions.begin() as session:
            await session.execute(update(AuthSession).where(AuthSession.token_hash == token_digest(client.token))
                                  .values(expires_at=utcnow() + timedelta(seconds=1)))
    client.portal.call(expire_soon)
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json({'type': 'start', 'conversation_id': conversation['id']})
        assert ws.receive_json()['type'] == 'ready'
        assert ws.receive_json()['report']['end_reason'] == 'auth_expired'


def test_migration_downgrade_and_upgrade_in_isolated_test_database(client):
    from alembic import command
    from alembic.config import Config
    from app.core.paths import PROJECT_ROOT

    async def roundtrip():
        config = Config(str(PROJECT_ROOT / 'alembic.ini'))

        def migrate(connection):
            config.attributes['connection'] = connection
            command.downgrade(config, 'base')
            command.upgrade(config, 'head')

        async with client.database.engine.begin() as connection:
            await connection.run_sync(migrate)
        assert await client.database.ready()
    client.portal.call(roundtrip)


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='PostgreSQL role privileges need TEST_DATABASE_URL')
def test_runtime_role_can_use_api_but_cannot_rewrite_prompt_versions(client):
    import psycopg
    from psycopg import sql

    role = 'test_runtime_' + uuid4().hex
    schema = client.schema
    assert schema.startswith('test_') and role.startswith('test_runtime_')
    with psycopg.connect(client.pg_url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        try:
            connection.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            connection.execute(sql.SQL('GRANT SELECT, INSERT ON {}.users TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            for table in ['user_preferences', 'auth_sessions', 'conversations', 'daily_usage',
                          'usage_reservations', 'conversation_rate_windows']:
                connection.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON {}.{} TO {}').format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)))
            for table in ['prompt_versions', 'alembic_version']:
                connection.execute(sql.SQL('GRANT SELECT ON {}.{} TO {}').format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)))
            connection.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON {}.user_memories TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            connection.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON {}.knowledge_entries TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            connection.execute(sql.SQL('GRANT SELECT, UPDATE ON {}.knowledge_state TO {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            database = Database(client.app.state.settings, connect_args={
                'server_settings': {'search_path': schema, 'role': role},
            })
            with TestClient(create_app(client.app.state.settings, FakeProvider(), database)) as restricted:
                logged_in = restricted.post('/api/v1/auth/login', json={
                    'email': 'default@example.com', 'password': 'TestPassword123!',
                })
                assert logged_in.status_code == 200
                restricted.headers['Authorization'] = 'Bearer ' + logged_in.json()['access_token']
                assert restricted.get('/health/ready').status_code == 200
                assert restricted.patch('/api/v1/users/me/preferences', json={'memory_enabled': True}).status_code == 200
                memory = restricted.post('/api/v1/users/me/memories', json={'key': 'practice', 'content': 'Kotlin'})
                assert memory.status_code == 201
                entry = restricted.post('/api/v1/knowledge/entries', json={'title': 'Kotlin', 'content': 'Coroutines'})
                assert entry.status_code == 201, entry.text
                assert restricted.get('/api/v1/knowledge/search', params={'q': 'Coroutines'}).json()['items']
                assert restricted.delete('/api/v1/knowledge/entries/' + entry.json()['id']).status_code == 204
                assert restricted.get('/api/v1/admin/knowledge').status_code == 403
                created = restricted.post('/api/v1/conversations', json={})
                assert created.status_code == 201
                with restricted.websocket_connect('/ws/live') as socket:
                    socket.send_json({'type': 'start', 'conversation_id': created.json()['id']})
                    assert socket.receive_json()['type'] == 'ready'
                    socket.send_json({'type': 'stop'})
                    assert socket.receive_json()['report']['persisted'] is True
                assert restricted.get('/api/v1/usage/me').json()['sessions_settled'] == 1
                assert restricted.delete('/api/v1/users/me/memories/' + memory.json()['id']).status_code == 204

                async def overwrite():
                    async with database.sessions.begin() as session:
                        await session.execute(update(PromptVersion).values(instructions='UNAUTHORIZED'))
                with pytest.raises(SQLAlchemyError) as exc:
                    restricted.portal.call(overwrite)
                assert exc.value.orig.sqlstate == '42501'

                async def self_promote():
                    async with database.sessions.begin() as session:
                        await session.execute(update(User).values(is_admin=True))
                with pytest.raises(SQLAlchemyError) as exc:
                    restricted.portal.call(self_promote)
                assert exc.value.orig.sqlstate == '42501'
        finally:
            connection.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            connection.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM {}').format(
                sql.Identifier(schema), sql.Identifier(role)))
            connection.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
