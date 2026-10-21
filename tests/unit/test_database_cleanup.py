import asyncio
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest

from app.db.session import Database
from app.services.session_registry import SessionRegistry
from tests.helpers.fakes import settings


async def test_cancelled_sqlite_checkout_closes_connection_created_by_worker(monkeypatch, tmp_path):
    started, release = Event(), Event()
    raw_connections = []
    original = sqlite3.connect

    def delayed_connect(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise RuntimeError('Test did not release the connection worker')
        raw = original(*args, **kwargs)
        raw_connections.append(raw)
        return raw

    monkeypatch.setattr(sqlite3, 'connect', delayed_connect)
    database = Database(settings(database_url=f'sqlite+aiosqlite:///{tmp_path / "cancelled.db"}'))

    async def checkout():
        async with database.engine.connect():
            pytest.fail('Cancelled checkout must not be handed to the caller')

    task = asyncio.create_task(checkout())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(3):
                await task
        assert len(raw_connections) == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            raw_connections[0].execute('SELECT 1')
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await database.close()
        for raw in raw_connections:
            raw.close()


async def test_shutdown_drains_in_flight_maintenance_without_cancelling_it():
    registry = SessionRegistry(SimpleNamespace(settings=settings(lease_heartbeat_seconds=.1), database=None))
    entered, release = asyncio.Event(), asyncio.Event()
    cancelled = False

    async def transaction():
        nonlocal cancelled
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    registry.maintain_once = transaction
    registry.maintenance = asyncio.create_task(registry.maintain())
    async with asyncio.timeout(3):
        await entered.wait()
        closing = asyncio.create_task(registry.close())
        await asyncio.sleep(.02)
        try:
            assert not cancelled
            assert not closing.done()
        finally:
            release.set()
            await closing
    assert registry.maintenance.done()
    assert not cancelled
