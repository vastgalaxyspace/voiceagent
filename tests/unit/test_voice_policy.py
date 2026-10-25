from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.integrations.gemini.live import GeminiProvider
from app.schemas.live import StartMessage
from app.services.prompt_builder import compose_prompt
from tests.helpers.fakes import settings


@pytest.mark.parametrize('overrides,proactive', [
    ({}, True),
    ({'voice_proactive_audio': False}, False),
    ({'gemini_model': 'gemini-3.1-flash-live-preview'}, False),
    ({'gemini_api_version': 'v1alpha'}, False),
])
async def test_voice_config_is_applied_on_resumption_and_gates_supported_features(monkeypatch, overrides, proactive):
    seen = {}

    class FakeAio:
        @property
        def live(self):
            return self

        @asynccontextmanager
        async def connect(self, **kwargs):
            seen.update(kwargs)
            yield SimpleNamespace(setup_complete=object())

        async def aclose(self):
            pass

    monkeypatch.setattr('app.integrations.gemini.live.genai.Client',
                        lambda **kwargs: SimpleNamespace(aio=FakeAio()))
    config = settings(voice_start_sensitivity='high', voice_prefix_padding_ms=100,
                      voice_silence_duration_ms=800, **overrides)
    async with GeminiProvider(config).connect('instructions', resume_handle='checkpoint'):
        pass
    sent = seen['config']
    assert sent.session_resumption.handle == 'checkpoint'
    detection = sent.realtime_input_config.automatic_activity_detection
    assert detection.start_of_speech_sensitivity.value == 'START_SENSITIVITY_HIGH'
    assert detection.prefix_padding_ms == 100
    assert detection.silence_duration_ms == 800
    assert bool(sent.proactivity and sent.proactivity.proactive_audio) == proactive


@pytest.mark.parametrize('overrides', [
    {'voice_start_sensitivity': 'invalid'},
    {'voice_prefix_padding_ms': -1},
    {'voice_prefix_padding_ms': 501},
    {'voice_silence_duration_ms': 99},
    {'voice_silence_duration_ms': 2001},
])
def test_invalid_voice_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_voice_rules_are_added_even_with_a_published_prompt():
    prompt = compose_prompt(StartMessage(type='start'), instructions='PUBLISHED_RULES')
    assert prompt.startswith('PUBLISHED_RULES')
    assert 'stop/wait' in prompt
    assert 'standalone hmm' in prompt
    assert 'confirms a choice' in prompt
    assert 'television' in prompt
