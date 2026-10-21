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

    async def end_audio(self):
        async with self.send_lock:
            await self.session.send_realtime_input(audio_stream_end=True)

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
    def __init__(self, settings: Settings):
        self.settings = settings

    @asynccontextmanager
    async def connect(self, prompt: str, *, resume_handle: str | None = None):
        client = genai.Client(
            api_key=self.settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(api_version=self.settings.gemini_api_version),
        )
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'], system_instruction=prompt,
            session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        )
        if self.settings.live_tools_enabled:
            config.tools = declarations()
        if self.settings.context_compression:
            config.context_window_compression = types.ContextWindowCompressionConfig(
                trigger_tokens=16000,
                sliding_window=types.SlidingWindow(target_tokens=8000),
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
