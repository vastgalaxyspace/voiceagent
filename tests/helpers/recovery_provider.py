"""Scriptable checkpoints and transport failures; no real provider calls."""
from contextlib import asynccontextmanager

from google.genai import types

from tests.helpers.fakes import FakeConnection


class RecoveryConnection(FakeConnection):
    def __init__(self):
        super().__init__()
        self.closed = False

    async def messages(self):
        while True:
            item = await self.queue.get()
            if isinstance(item, Exception):
                raise item
            yield item


class RecoveryProvider:
    def __init__(self):
        self.connections = []
        self.handles = []
        self.fail_resumes = []

    @asynccontextmanager
    async def connect(self, prompt, *, resume_handle=None):
        self.handles.append(resume_handle)
        if resume_handle and self.fail_resumes:
            raise self.fail_resumes.pop(0)
        connection = RecoveryConnection()
        self.connections.append(connection)
        await connection.queue.put(types.LiveServerMessage(
            session_resumption_update=types.LiveServerSessionResumptionUpdate(
                resumable=True, new_handle=f'PRIVATE_HANDLE_{len(self.connections)}',
            ),
        ))
        try:
            yield connection
        finally:
            connection.closed = True
