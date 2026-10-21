from contextlib import asynccontextmanager
from types import SimpleNamespace
import asyncio
import pytest
from app.integrations.gemini.live import GeminiConnection, GeminiProvider
from tests.helpers.fakes import settings


async def test_sdk_receive_restarts_for_each_turn():
    class SDKSession:
        def __init__(self):
            self.calls = 0

        async def receive(self):
            self.calls += 1
            yield self.calls

    sdk_session = SDKSession()
    iterator = GeminiConnection(sdk_session).messages()
    assert await anext(iterator) == 1
    assert await anext(iterator) == 2
    await iterator.aclose()


@pytest.mark.parametrize('tools_enabled', [False, True])
async def test_real_adapter_config_and_context_lifecycle(monkeypatch, tools_enabled):
    seen = {}

    class FakeAio:
        def __init__(self):
            self.live = self

        @asynccontextmanager
        async def connect(self, *, model, config):
            seen['model'], seen['config'] = model, config
            yield SimpleNamespace(setup_complete=object())

        async def aclose(self):
            seen['closed'] = True

    class Client:
        def __init__(self, **kwargs):
            self.aio = FakeAio()

    monkeypatch.setattr('app.integrations.gemini.live.genai.Client', Client)
    async with GeminiProvider(settings(context_compression=True, live_tools_enabled=tools_enabled)).connect('test instructions'):
        pass
    assert seen['model'] == 'gemini-3.8-live'
    assert seen['config'].input_audio_transcription is None
    assert seen['config'].session_resumption.handle is None
    assert seen['config'].context_window_compression.sliding_window.target_tokens == 8000
    assert seen['closed']
    if tools_enabled:
        declarations = seen['config'].tools[0].function_declarations
        assert {item.name for item in declarations} == {'search_knowledge', 'get_knowledge_entry', 'get_usage_allowance'}
        assert all(item.behavior.value == 'BLOCKING' for item in declarations)
        assert all(item.parameters_json_schema['additionalProperties'] is False for item in declarations)
    else:
        assert seen['config'].tools is None


async def test_sdk_serializes_audio_and_tool_writes_and_preserves_call_identity():
    seen = []
    busy = False

    class SDKSession:
        async def write(self, value):
            nonlocal busy
            assert not busy
            busy = True
            await asyncio.sleep(.01)
            seen.append(value)
            busy = False

        async def send_realtime_input(self, **kwargs):
            await self.write(kwargs)

        async def send_tool_response(self, **kwargs):
            await self.write(kwargs)

    connection = GeminiConnection(SDKSession())
    await asyncio.gather(connection.send_audio(b'\0\0'), connection.end_audio(),
                         connection.send_tool_responses([{'id': 'call-7', 'name': 'get_usage_allowance',
                                                          'response': {'ok': True}}]))
    response = seen[2]['function_responses'][0]
    assert response.id == 'call-7' and response.name == 'get_usage_allowance'
    assert response.response == {'ok': True}
