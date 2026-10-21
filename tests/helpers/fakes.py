"""Simulated provider and shared helpers; no paid API calls."""
import asyncio
from contextlib import asynccontextmanager

from google.genai import types

from app.core.config import Settings

class FakeConnection:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.audio = []
        self.ended = False

    async def send_audio(self, data):
        self.audio.append(data)
        await self.queue.put(types.LiveServerMessage(server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(
                data=b'\0\0' * 240, mime_type='audio/pcm;rate=24000',
            ))]),
        )))
        if len(self.audio) == 2:
            await self.queue.put(types.LiveServerMessage(server_content=types.LiveServerContent(interrupted=True)))
        await self.queue.put(types.LiveServerMessage(
            server_content=types.LiveServerContent(turn_complete=True),
            usage_metadata=usage(10, 5),
        ))

    async def end_audio(self):
        self.ended = True

    async def messages(self):
        while True:
            yield await self.queue.get()

class FakeProvider:
    def __init__(self, fail=False, delay=0):
        self.connection = None
        self.opened = False
        self.closed = False
        self.fail, self.delay = fail, delay

    @asynccontextmanager
    async def connect(self, prompt, *, resume_handle=None):
        self.opened = True
        self.last_prompt = prompt
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError('SENSITIVE_PROVIDER_ERROR')
            self.connection = FakeConnection()
            yield self.connection
        finally:
            self.closed = True

def usage(input_count, output_count, **kwargs):
    return types.UsageMetadata(
        prompt_token_count=input_count, response_token_count=output_count,
        prompt_tokens_details=[types.ModalityTokenCount(modality='AUDIO', token_count=input_count)],
        response_tokens_details=[types.ModalityTokenCount(modality='AUDIO', token_count=output_count)],
        **kwargs,
    )

def settings(**kwargs):
    values = {'database_url': '', 'migration_database_url': '', 'gemini_api_key': '',
              'client_reconnect_grace_seconds': .15, 'provider_resume_backoff_seconds': .01}
    values.update(kwargs)
    values.setdefault('minimum_session_seconds', min(30, values.get('session_max_seconds', 300)))
    return Settings(_env_file=None, **values)

def start(ws):
    ws.send_json({'type': 'start', 'language': 'English', 'goal': 'Practise speaking'})
    message = ws.receive_json()
    assert message['type'] == 'ready'
    return message
