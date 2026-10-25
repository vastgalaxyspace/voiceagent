from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import Settings
from app.core.security import Admission, TransportMiddleware
from app.main import create_app
from app.services.operations import Operations


def production(**overrides):
    values = dict(environment='production', public_origin='https://voice.example.com',
                  database_url='postgresql+asyncpg://runtime:synthetic@db/voice?ssl=verify-full', gemini_api_key='synthetic',
                  registration_enabled=False, enable_api_docs=False, enable_test_harness=False,
                  save_reports=False, migration_database_url='')
    values.update(overrides)
    return Settings(_env_file=None, **values)


def app_for_transport(**overrides):
    database = SimpleNamespace(ready=AsyncMock(return_value=True), close=AsyncMock())
    return create_app(production(**overrides), database=database)


@pytest.mark.parametrize('overrides', [
    {'public_origin': ''}, {'public_origin': 'http://voice.example.com'},
    {'public_origin': 'https://voice.example.com/path'}, {'public_origin': 'https://user:pass@voice.example.com'},
    {'public_origin': 'https://voice.example.com/?token=x'}, {'public_origin': 'https://*.example.com'},
    {'database_url': 'sqlite+aiosqlite:///test.db'}, {'gemini_api_key': ''},
    {'database_url': 'postgresql+asyncpg://runtime:synthetic@db/voice'},
    {'database_url': 'postgresql+asyncpg://runtime:synthetic@db/voice?ssl=require'},
    {'migration_database_url': 'postgresql+asyncpg://owner:secret@db/voice'},
    {'registration_enabled': True}, {'enable_api_docs': True}, {'enable_test_harness': True}, {'save_reports': True},
    {'save_output_audio': True},
])
def test_production_rejects_unsafe_configuration(overrides):
    with pytest.raises(ValidationError):
        production(**overrides)


def test_settings_load_file_secrets_without_embedding_values(tmp_path):
    (tmp_path / 'database_url').write_text('postgresql+asyncpg://runtime:synthetic@db/voice', encoding='utf-8')
    (tmp_path / 'gemini_api_key').write_text('FILE_SECRET', encoding='utf-8')
    configured = Settings(_env_file=None, _secrets_dir=tmp_path)
    assert configured.gemini_api_key.get_secret_value() == 'FILE_SECRET'
    assert 'FILE_SECRET' not in repr(configured)


def test_production_https_host_origin_and_hidden_surfaces():
    client = TestClient(app_for_transport(), base_url='https://voice.example.com', client=('198.51.100.5', 1000))
    response = client.get('/health')
    assert response.status_code == 200 and response.json()['phase'] == 8
    assert response.headers['strict-transport-security'] == 'max-age=31536000'
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/health', headers={'Origin': 'https://foreign.example'}).status_code == 403
    assert client.get('/health', headers={'Host': 'foreign.example'}).status_code == 400
    for path in ('/', '/docs', '/openapi.json', '/static/client.js'):
        assert client.get(path).status_code == 404
    assert client.post('/api/v1/auth/register', json={
        'email': 'tester@example.com', 'password': 'Syn123!',
    }).json()['error'] == 'registration_disabled'


def test_forwarded_headers_only_work_from_the_configured_proxy():
    application = ProxyHeadersMiddleware(app_for_transport(), trusted_hosts=['172.30.8.2'])
    headers = {'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '198.51.100.5'}
    untrusted = TestClient(application, base_url='http://voice.example.com', client=('198.51.100.5', 1000))
    assert untrusted.get('/health', headers=headers).json()['error'] == 'secure_transport_required'
    trusted = TestClient(application, base_url='http://voice.example.com', client=('172.30.8.2', 1000))
    assert trusted.get('/health', headers=headers).status_code == 200
    assert untrusted.get('/api/v1/auth/login', headers=headers).status_code == 400


def test_loopback_probe_does_not_allow_insecure_api_calls():
    client = TestClient(app_for_transport(), base_url='http://127.0.0.1', client=('127.0.0.1', 1000))
    assert client.get('/health/ready').status_code == 200
    assert client.get('/api/v1/auth/login').status_code == 400


def test_websocket_origin_secure_transport_and_native_client():
    client = TestClient(app_for_transport(), base_url='https://voice.example.com', client=('198.51.100.5', 1000))
    from starlette.websockets import WebSocketDisconnect
    for url, headers in [('ws://voice.example.com/ws/live', {}),
                         ('wss://voice.example.com/ws/live', {'Origin': 'https://foreign.example'})]:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url, headers=headers):
                pass
    with client.websocket_connect('wss://voice.example.com/ws/live') as socket:
        socket.send_json({'type': 'start', 'conversation_id': str(uuid4())})
        assert socket.receive_json()['code'] == 'authentication_required'


def test_auth_rate_limit_rejects_before_password_work(monkeypatch):
    from app.core.errors import AppError
    login = AsyncMock(side_effect=AppError('invalid_credentials', 401))
    monkeypatch.setattr('app.api.routes.auth.auth.login', login)
    client = TestClient(app_for_transport(auth_requests_per_minute=2), base_url='https://voice.example.com')
    body = {'email': 'tester@example.com', 'password': 'SyntheticPassword123!'}
    assert client.post('/api/v1/auth/login', json=body).status_code == 401
    assert client.post('/api/v1/auth/login', json=body).status_code == 401
    rejected = client.post('/api/v1/auth/login/', json=body, follow_redirects=False)
    assert rejected.status_code == 429 and rejected.headers['retry-after'] == '60'
    assert login.await_count == 2


def test_admission_global_cap_inflight_and_window_reset(monkeypatch):
    now = [100]
    monkeypatch.setattr('app.core.security.monotonic', lambda: now[0])
    admission = Admission(production(auth_max_inflight=1, auth_global_requests_per_minute=2))
    assert admission.enter('first')
    assert not admission.enter('second')
    admission.inflight -= 1
    assert admission.enter('second')
    admission.inflight -= 1
    assert not admission.enter('third') and len(admission.buckets) == 2
    now[0] += 61
    assert admission.enter('third') and len(admission.buckets) == 1


@pytest.mark.parametrize('chunks,length,expected', [
    ([b'hello'], None, 200), ([b'x' * 20000, b'y' * 20000], None, 413),
    ([], b'99999', 413), ([], b'invalid', 400),
])
async def test_http_body_is_bounded_before_handler(chunks, length, expected):
    received, sent = [], []
    messages = [{'type': 'http.request', 'body': chunk, 'more_body': index < len(chunks) - 1}
                for index, chunk in enumerate(chunks)]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def inner(scope, receive, send):
        received.append(await receive())
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})

    middleware = TransportMiddleware(inner, production(), Operations())
    await middleware({'type': 'http', 'scheme': 'https', 'path': '/bounded', 'client': ('198.51.100.5', 1),
                      'method': 'POST', 'headers': [(b'content-length', length)] if length else []}, receive, send)
    assert sent[0]['status'] == expected
    assert bool(received) is (expected == 200)
    if received:
        assert received[0]['body'] == b'hello'


def test_startup_refuses_unmigrated_production_database():
    app = app_for_transport()
    app.state.database.ready.return_value = False
    with pytest.raises(RuntimeError, match='migration'):
        with TestClient(app):
            pass
    app.state.database.close.assert_awaited_once()


def test_operations_log_excludes_sensitive_request_fields(caplog):
    import logging
    client = TestClient(app_for_transport(), base_url='https://voice.example.com')
    with caplog.at_level(logging.INFO, logger='voiceagent.http'):
        client.get('/missing?secret=DO_NOT_LOG_QUERY', headers={'Authorization': 'Bearer DO_NOT_LOG_TOKEN'})
    assert 'http_request' in caplog.text
    assert 'DO_NOT_LOG' not in caplog.text
