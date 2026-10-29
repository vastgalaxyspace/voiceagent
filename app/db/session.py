import asyncio

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
import anyio

from app.core.config import Settings


async def open_sqlite(*args, **kwargs):
    """Finish an in-flight connect and close it if its owner is cancelled.

    Cancelling aiosqlite.connect() directly can lose the raw SQLite connection
    created by its worker thread before it is assigned to the async proxy.
    """
    import aiosqlite  # SQLite is a test-only dependency; PostgreSQL does not load it.

    with anyio.CancelScope(shield=True):
        opening = asyncio.ensure_future(aiosqlite.connect(*args, **kwargs))
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            connection = await opening
            await connection.close()
            raise


class Database:
    def __init__(self, settings: Settings, *, connect_args: dict | None = None):
        url = settings.database_url.get_secret_value()
        options = {'pool_pre_ping': True, 'hide_parameters': True}
        if url.startswith('postgresql'):
            options.update(pool_size=settings.database_pool_size,
                           max_overflow=settings.database_max_overflow, pool_timeout=5)
        else:
            options['poolclass'] = NullPool
        if url.startswith('sqlite'):
            parsed = make_url(url)
            args, params = parsed.get_dialect()().create_connect_args(parsed)
            params.update(connect_args or {})
            options['async_creator'] = lambda: open_sqlite(*args, **params)
        self.engine = create_async_engine(url, connect_args=connect_args or {}, **options)
        if url.startswith('sqlite'):
            @event.listens_for(self.engine.sync_engine, 'connect')
            def enable_foreign_keys(connection, _):
                cursor = connection.cursor()
                cursor.execute('PRAGMA foreign_keys=ON')
                cursor.close()
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ready(self) -> bool:
        async with self.sessions() as session:
            # Validate the migration marker, not merely database reachability.
            version = await session.scalar(text('SELECT version_num FROM alembic_version'))
            return version == '0007_context_continuation'

    async def close(self):
        with anyio.CancelScope(shield=True):
            await self.engine.dispose()
