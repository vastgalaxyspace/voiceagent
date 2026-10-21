from sqlalchemy import update

from app.db.models import User
from app.main import create_app
from tests.helpers.database import FoundationClient
from tests.helpers.fakes import FakeProvider, settings


def test_drain_requires_admin_preserves_live_session_and_blocks_new_admission():
    with FoundationClient(create_app(settings(), FakeProvider())) as client:
        assert client.get('/api/v1/admin/operations').status_code == 403
        assert client.post('/api/v1/admin/drain').status_code == 403

        async def promote():
            async with client.database.sessions.begin() as session:
                await session.execute(update(User).values(is_admin=True))
        client.portal.call(promote)
        row = client.post('/api/v1/conversations', json={}).json()
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': row['id']})
            assert socket.receive_json()['type'] == 'ready'
            assert client.post('/api/v1/admin/drain').json()['active_sessions'] == 1
            assert client.get('/health/ready').status_code == 503
            assert client.get('/health').status_code == 200
            assert client.get('/api/v1/admin/operations').json()['draining']
            socket.send_bytes(b'\0\0' * 320)
            assert socket.receive_bytes()
            assert socket.receive_json()['type'] == 'turn_complete'
            socket.send_json({'type': 'stop'})
            assert socket.receive_json()['report']['end_reason'] == 'user_stopped'
        next_row = client.post('/api/v1/conversations', json={}).json()
        with client.websocket_connect('/ws/live') as socket:
            socket.send_json({'type': 'start', 'conversation_id': next_row['id']})
            assert socket.receive_json()['code'] == 'server_draining'
        assert client.get('/api/v1/usage/me').json()['reserved_seconds'] == 0
