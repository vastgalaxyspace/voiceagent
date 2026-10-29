import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

import anyio

from google import genai
from google.genai import types

from app.core.config import Settings
from app.integrations.gemini.tool_schema import declarations


class GeminiConnection:
    def __init__(self, session):
        self.session = session
        self.send_lock = asyncio.Lock()

    async def send_audio(self, data: bytes):
        async with self.send_lock:
            await self.session.send_realtime_input(
                audio=types.Blob(data=data, mime_type='audio/pcm;rate=16000')
            )

    async def greet(self):
        # A single initial turn requests real provider speech, rather than client TTS.
        async with self.send_lock:
            await self.session.send_client_content(
                turns={'role': 'user', 'parts': [{'text':
                    'Begin this voice conversation now. If prior conversation context is supplied, '
                    'briefly offer to continue its unfinished topic instead of a generic greeting. '
                    'Otherwise say hello warmly in the '
                    'preferred conversation language, then briefly ask how you can help. '
                    'Keep the greeting to one or two short sentences.'}]},
                turn_complete=True,
            )

    async def end_audio(self):
        async with self.send_lock:
            await self.session.send_realtime_input(audio_stream_end=True)

    async def activity_start(self):
        async with self.send_lock:
            await self.session.send_realtime_input(activity_start=types.ActivityStart())

    async def activity_end(self):
        async with self.send_lock:
            await self.session.send_realtime_input(activity_end=types.ActivityEnd())

    async def send_tool_responses(self, responses):
        async with self.send_lock:
            await self.session.send_tool_response(function_responses=[
                types.FunctionResponse(**response) for response in responses
            ])

    async def messages(self):
        # receive() completes after one model turn, not the whole conversation.
        while True:
            seen = False
            async for message in self.session.receive():
                seen = True
                yield message
            if not seen:
                raise ConnectionError('Provider receive stream ended')


class GeminiProvider:
    def __init__(self, settings: Settings, *, client_vad: bool = False):
        self.settings = settings
        self.client_vad = client_vad

    @asynccontextmanager
    async def connect(self, prompt: str, *, resume_handle: str | None = None):
        client = genai.Client(
            api_key=self.settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(api_version=self.settings.gemini_api_version),
        )
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'], system_instruction=prompt,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(handle=resume_handle),
            realtime_input_config=types.RealtimeInputConfig(
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                automatic_activity_detection=(types.AutomaticActivityDetection(disabled=True)
                    if self.client_vad else types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=(types.StartSensitivity.START_SENSITIVITY_LOW
                        if self.settings.voice_start_sensitivity == 'low'
                        else types.StartSensitivity.START_SENSITIVITY_HIGH),
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=self.settings.voice_prefix_padding_ms,
                    silence_duration_ms=self.settings.voice_silence_duration_ms,
                )),
            ),
        )
        # Proactive audio is documented for 3.8 Live on v1beta, not 3.1.
        # It can decline irrelevant input, but cannot undo a VAD interruption.
        if (self.settings.voice_proactive_audio and self.settings.gemini_model == 'gemini-3.8-live'
                and self.settings.gemini_api_version == 'v1beta'):
            config.proactivity = types.ProactivityConfig(proactive_audio=True)
        if self.settings.live_tools_enabled:
            config.tools = declarations()
        if self.settings.context_compression:
            config.context_window_compression = types.ContextWindowCompressionConfig(
                trigger_tokens=self.settings.context_trigger_tokens,
                sliding_window=types.SlidingWindow(target_tokens=self.settings.context_target_tokens),
            )
        stack = AsyncExitStack()
        try:
            session = await stack.enter_async_context(client.aio.live.connect(
                model=self.settings.gemini_model, config=config,
            ))
            if session.setup_complete is None:
                raise ConnectionError('Provider did not confirm session setup')
            yield GeminiConnection(session)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    async with asyncio.timeout(self.settings.io_timeout_seconds):
                        await stack.aclose()
                finally:
                    async with asyncio.timeout(self.settings.io_timeout_seconds):
                        await client.aio.aclose()
