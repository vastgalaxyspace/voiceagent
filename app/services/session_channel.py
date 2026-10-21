"""A bounded, replaceable client transport owned by a conversation runtime."""
import asyncio
from time import monotonic

from app.core.errors import AppError


class SessionChannel:
    def __init__(self, io_timeout: float):
        self.io_timeout = io_timeout
        self.incoming = asyncio.Queue(maxsize=8)
        self.socket = None
        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.disconnected.set()
        self.detached_at = monotonic()
        self.last_received = monotonic()
        self.epoch = 0
        self.stop_reason = None

    def _clear(self):
        while not self.incoming.empty():
            self.incoming.get_nowait()

    def attach(self, socket):
        if self.socket is not None:
            raise AppError('conversation_already_attached', 409)
        self._clear()
        self.socket = socket
        self.epoch += 1
        self.last_received = monotonic()
        self.disconnected.clear()
        self.connected.set()
        self.incoming.put_nowait({'type': 'client.attached'})

    def detach(self, socket):
        if self.socket is not socket:
            return
        self.socket = None
        self._clear()
        self.detached_at = monotonic()
        self.connected.clear()
        self.disconnected.set()
        self.incoming.put_nowait({'type': 'client.detached'})

    def stop(self, reason: str):
        self.stop_reason = self.stop_reason or reason
        self._clear()
        self.incoming.put_nowait({'type': 'session.stop'})

    def forward(self, socket, message):
        if self.socket is not socket:
            return
        self.last_received = monotonic()
        try:
            self.incoming.put_nowait(message)
        except asyncio.QueueFull:
            self.stop('input_backpressure')

    async def receive(self):
        return await self.incoming.get()

    async def _send(self, value, *, binary=False):
        socket = self.socket
        if socket is None:
            return  # Output is never buffered across a detached client.
        try:
            async with asyncio.timeout(self.io_timeout):
                if binary:
                    await socket.send_bytes(value)
                else:
                    await socket.send_json(value)
        except Exception:
            self.detach(socket)

    async def send_bytes(self, value):
        await self._send(value, binary=True)

    async def send_json(self, value):
        await self._send(value)

    async def expire_transport(self):
        socket = self.socket
        if socket is None:
            return
        self.detach(socket)
        try:
            async with asyncio.timeout(self.io_timeout):
                await socket.close(code=1012)
        except Exception:
            pass
