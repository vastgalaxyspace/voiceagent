import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from tests.helpers.database import FoundationClient as TestClient
from google.genai import types
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.helpers.fakes import FakeProvider, settings, start


def test_health_and_test_client_do_not_need_credentials():
    with TestClient(create_app(settings())) as client:
        assert client.get('/health').json()['configured'] is False
        assert client.get('/').status_code == 200
        assert client.get('/static/capture-worklet.js').status_code == 200
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start'})
            assert ws.receive_json()['code'] == 'missing_api_key'


def test_audio_multiple_turns_interruption_usage_and_cleanup():
    provider = FakeProvider()
    with TestClient(create_app(settings(usage_mode='per_response'), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws)
            for turn in range(2):
                ws.send_bytes(b'\xe8\x03' * 320)
                events = []
                while True:
                    event = ws.receive()
                    if event.get('bytes') is not None:
                        assert len(event['bytes']) == 480
                    else:
                        control = json.loads(event['text'])
                        events.append(control['type'])
                        if control['type'] == 'turn_complete':
                            break
                if turn == 1:
                    assert 'interrupted' in events
            ws.send_json({'type': 'stop'})
            report = ws.receive_json()['report']
            assert report['end_reason'] == 'user_stopped'
            assert report['turn_count'] == 2
            assert report['interruption_count'] == 1
            assert report['input_audio_seconds'] == .04
            assert report['estimated_model_cost_usd'] == .00018
        assert provider.closed
        assert not client.get('/health').json()['active_session']


def test_only_one_active_session_and_slot_reusable():
    provider = FakeProvider()
    with TestClient(create_app(settings(), provider)) as client:
        with client.websocket_connect('/ws/live') as first:
            start(first)
            with client.websocket_connect('/ws/live') as second:
                second.send_json({'type': 'start'})
                assert second.receive_json()['code'] == 'session_busy'
            first.send_json({'type': 'stop'})
            assert first.receive_json()['type'] == 'ended'
        with client.websocket_connect('/ws/live') as third:
            start(third)
            third.send_json({'type': 'stop'})
            assert third.receive_json()['type'] == 'ended'


@pytest.mark.parametrize('payload', [b'\x01', b'\0' * 3202, b''])
def test_invalid_pcm_closes_provider(payload):
    provider = FakeProvider()
    with TestClient(create_app(settings(), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws)
            ws.send_bytes(payload)
            assert ws.receive_json()['report']['end_reason'] == 'invalid_audio'
        assert provider.closed


@pytest.mark.parametrize('payload', [{'type': 'other'}, {'type': 'start', 'goal': 'x' * 501}, []])
def test_invalid_start_never_opens_provider(payload):
    provider = FakeProvider()
    with TestClient(create_app(settings(), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json(payload)
            assert ws.receive_json()['code'] == 'invalid_start'
        assert not provider.opened


def test_foreign_origin_rejected():
    with TestClient(create_app(settings(), FakeProvider())) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect('/ws/live', headers={'origin': 'https://unrelated.example'}):
                pass
        assert exc.value.code == 1008


@pytest.mark.parametrize(('options', 'reason'), [
    ({'session_max_seconds': .15}, 'duration_limit'),
    ({'session_idle_seconds': .15}, 'idle_timeout'),
])
def test_watchdog_closes_provider(options, reason):
    provider = FakeProvider()
    with TestClient(create_app(settings(**options), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            start(ws)
            assert ws.receive_json()['report']['end_reason'] == reason
        assert provider.closed


def test_setup_timeout_cleans_up():
    provider = FakeProvider(delay=1)
    with TestClient(create_app(settings(provider_setup_seconds=.05), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start'})
            assert ws.receive_json()['report']['end_reason'] == 'io_or_setup_timeout'
        assert provider.closed


def test_setup_exception_does_not_expose_provider_message():
    provider = FakeProvider(fail=True)
    with TestClient(create_app(settings(), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start'})
            response = ws.receive_json()
            assert response['report']['end_reason'] == 'provider_error'
            assert 'SENSITIVE' not in json.dumps(response)
        assert provider.closed


def test_disconnect_during_setup_cancels_provider():
    provider = FakeProvider(delay=1)
    app = create_app(settings(), provider)
    with TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start'})
            # A stop must be handled without waiting for provider readiness.
            ws.send_json({'type': 'stop'})
            assert ws.receive_json()['report']['end_reason'] == 'user_stopped'
        assert provider.closed
        assert not app.state.active


def test_abrupt_disconnect_closes_provider_and_releases_slot():
    provider = FakeProvider()
    app = create_app(settings(), provider)

    async def wait_for_cleanup():
        async with asyncio.timeout(2):
            while app.state.active or not provider.closed:
                await asyncio.sleep(.01)

    with TestClient(app) as client:
        with client.websocket_connect('/ws/live') as ws:
            ready = start(ws)
        client.portal.call(wait_for_cleanup)
        assert provider.closed
        assert not app.state.active
        stored = client.get('/api/v1/conversations/' + ready['session_id']).json()
        assert stored['status'] in {'ended', 'failed'}
        assert stored['ended_at'] is not None


def test_provider_goaway_ends_explicitly():
    class GoAwayProvider(FakeProvider):
        @asynccontextmanager
        async def connect(self, prompt, *, resume_handle=None):
            async with super().connect(prompt, resume_handle=resume_handle) as connection:
                await connection.queue.put(types.LiveServerMessage(
                    go_away=types.LiveServerGoAway(time_left='10s'),
                ))
                yield connection

    provider = GoAwayProvider()
    with TestClient(create_app(settings(), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start'})
            message = ws.receive_json()
            while message['type'] != 'ended':
                message = ws.receive_json()
            assert message['report']['end_reason'] == 'provider_go_away'
        assert provider.closed


def test_saved_report_excludes_user_prompt_and_credentials(tmp_path):
    provider = FakeProvider()
    with TestClient(create_app(settings(save_reports=True, gemini_api_key='PRIVATE_KEY', reports_directory=tmp_path / 'reports'), provider)) as client:
        with client.websocket_connect('/ws/live') as ws:
            ws.send_json({'type': 'start', 'goal': 'PRIVATE_GOAL'})
            assert ws.receive_json()['type'] == 'ready'
            ws.send_json({'type': 'stop'})
            assert ws.receive_json()['type'] == 'ended'
    paths = list((tmp_path / 'reports').glob('*.json'))
    assert len(paths) == 1
    text = paths[0].read_text(encoding='utf-8')
    assert 'PRIVATE_GOAL' not in text
    assert 'PRIVATE_KEY' not in text
    assert json.loads(text)['end_reason'] == 'user_stopped'
