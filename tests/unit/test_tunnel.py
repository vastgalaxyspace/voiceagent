from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app


def application(**overrides):
    values = dict(environment='tunnel', public_origin='https://voice.example.com')
    values.update(overrides)
    return create_app(Settings(_env_file=None, **values),
                      database=SimpleNamespace(ready=AsyncMock(return_value=True), close=AsyncMock()))


def test_tunnel_requires_explicit_origin_and_no_debug_recording():
    for values in ({'public_origin': ''}, {'public_origin': 'http://voice.example.com'},
                   {'save_output_audio': True}, {'save_reports': True}):
        with pytest.raises(ValidationError):
            application(**values)


def test_public_tunnel_accepts_remote_users_and_preserves_boundaries(monkeypatch):
    register = AsyncMock(side_effect=AppError('reached_registration', 409))
    monkeypatch.setattr('app.api.routes.auth.auth.register', register)
    client = TestClient(application(), base_url='https://voice.example.com',
                        client=('198.51.100.7', 1000))
    assert client.get('/').status_code == 200
    assert client.get('/health').status_code == 200
    response = client.post('/api/v1/auth/register', json={'email': 'user@example.com', 'password': 'Test123!'})
    assert response.json()['error'] == 'reached_registration'
    assert register.await_count == 1
    assert client.get('/health', headers={'Origin': 'https://foreign.example'}).status_code == 403
    assert client.get('/health', headers={'Host': 'foreign.example'}).status_code == 400
    assert client.get('http://voice.example.com/health').status_code == 400


def test_only_local_tunnel_agent_can_forward_https():
    app = ProxyHeadersMiddleware(application(), trusted_hosts=['127.0.0.1', '::1'])
    headers = {'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '198.51.100.7'}
    local = TestClient(app, base_url='http://voice.example.com', client=('127.0.0.1', 1000))
    remote = TestClient(app, base_url='http://voice.example.com', client=('198.51.100.7', 1000))
    assert local.get('/health', headers=headers).status_code == 200
    assert remote.get('/health', headers=headers).json()['error'] == 'secure_transport_required'


def test_public_tunnel_limits_auth_requests(monkeypatch):
    monkeypatch.setattr('app.api.routes.auth.auth.login', AsyncMock(side_effect=AppError('invalid_credentials', 401)))
    client = TestClient(application(auth_requests_per_minute=1), base_url='https://voice.example.com')
    body = {'email': 'user@example.com', 'password': 'Test123!'}
    assert client.post('/api/v1/auth/login', json=body).status_code == 401
    assert client.post('/api/v1/auth/login', json=body).status_code == 429
