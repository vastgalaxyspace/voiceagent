import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from google.genai import types

from app.integrations.gemini.live import GeminiConnection
from app.services.live_session import Relay
from app.services.usage import Measurements
from tests.helpers.fakes import settings


async def test_greeting_requests_a_real_complete_provider_turn():
    calls = []

    class Session:
        async def send_client_content(self, **kwargs):
            calls.append(kwargs)

    await GeminiConnection(Session()).greet()
    assert len(calls) == 1
    assert calls[0]['turn_complete'] is True
    assert calls[0]['turns']['role'] == 'user'
    assert 'hello' in calls[0]['turns']['parts'][0]['text']
    assert 'preferred conversation language' in calls[0]['turns']['parts'][0]['text']


@pytest.mark.parametrize('first', [True, False])
async def test_initial_greeting_is_accounted_for_and_not_repeated_on_resume(first):
    calls = []

    class Connection:
        async def greet(self):
            calls.append('hello')

        async def messages(self):
            await asyncio.Event().wait()
            if False:
                yield None

    class Provider:
        @asynccontextmanager
        async def connect(self, prompt, *, resume_handle=None):
            yield Connection()

    measurements = Measurements('gemini-3.8-live', 'per_response')
    channel = SimpleNamespace(disconnected=asyncio.Event())
    relay = Relay(channel, settings(), Provider(), 'Speak naturally', measurements)
    relay.has_ready = not first
    task = asyncio.create_task(relay.connect_once(None if first else 'checkpoint'))
    try:
        ready = await asyncio.wait_for(relay.outbox.get(), 1)
        await asyncio.sleep(0)
        assert ready['type'] == ('ready' if first else 'resumed')
        assert ready['greeting_pending'] is first
        assert calls == (['hello'] if first else [])
        assert measurements.usage_pending is first
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_greeting_text_input_and_audio_output_use_existing_cost_accounting():
    measurements = Measurements('gemini-3.8-live', 'per_response')
    measurements.mark_input_activity()  # The greeting request, before provider I/O.

    class Connection:
        async def messages(self):
            yield types.LiveServerMessage(server_content=types.LiveServerContent(
                model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(
                    data=b'\0\0' * 240, mime_type='audio/pcm;rate=24000',
                ))]),
            ))
            yield types.LiveServerMessage(
                server_content=types.LiveServerContent(turn_complete=True),
                usage_metadata=types.UsageMetadata(
                    prompt_token_count=20, response_token_count=10,
                    prompt_tokens_details=[types.ModalityTokenCount(modality='TEXT', token_count=20)],
                    response_tokens_details=[types.ModalityTokenCount(modality='AUDIO', token_count=10)],
                ),
            )

    relay = Relay(None, settings(), None, '', measurements)
    with pytest.raises(ConnectionError):
        await relay.download(Connection())
    report = measurements.summary('user_stopped')
    assert report['aggregated_tokens'] == {'input_TEXT': 20, 'output_AUDIO': 10}
    assert report['estimated_model_cost_usd'] == pytest.approx(.000135)
    assert report['generated_audio_seconds'] == .01
    assert report['turn_count'] == 1
    assert report['usage_complete']
