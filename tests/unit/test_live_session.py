from types import SimpleNamespace

import pytest
from google.genai import types
from app.services.live_session import Outbox, Relay, SessionEnd
from app.services.usage import Measurements
from tests.helpers.fakes import settings, usage


async def test_interruption_clears_queued_audio_and_prioritizes_event():
    outbox = Outbox()
    outbox.put(b'stale audio')
    outbox.put({'type': 'turn_complete'})
    outbox.interrupt()
    assert await outbox.get() == {'type': 'interrupted'}
    assert await outbox.get() == {'type': 'turn_complete'}
    assert not outbox.items


def test_outbox_bounded_by_packet_count_and_audio_bytes():
    outbox = Outbox(limit=1)
    outbox.put(b'one')
    with pytest.raises(SessionEnd):
        outbox.put(b'two')
    with pytest.raises(SessionEnd):
        Outbox().put(b'\0' * 480001)


@pytest.mark.parametrize('enabled', [False, True])
async def test_generated_tool_call_makes_prior_complete_usage_uncertain(enabled):
    measurements = Measurements('gemini-3.8-live', 'per_response')
    measurements.record_usage(usage(10, 5))
    assert measurements.estimated_cost() is not None and not measurements.usage_pending
    calls = []

    class Connection:
        async def messages(self):
            yield types.LiveServerMessage(tool_call=types.LiveServerToolCall(function_calls=[
                types.FunctionCall(id='cancel-before-result', name='get_usage_allowance', args={}),
            ]))

    relay = Relay(None, settings(), None, '', measurements)
    tools = SimpleNamespace(submit=calls.extend) if enabled else None
    with pytest.raises(ConnectionError if enabled else SessionEnd):
        await relay.download(Connection(), tools)
    assert bool(calls) is enabled
    report = measurements.summary('user_stopped')
    assert report['unreported_provider_activity']
    assert report['estimated_model_cost_usd'] is None and not report['usage_complete']
