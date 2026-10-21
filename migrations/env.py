import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.db import models  # noqa: F401 - register every mapped table

config = context.config
target_metadata = Base.metadata


def configure(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def database_url():
    settings = Settings()
    value = (config.attributes.get('database_url') or settings.migration_database_url.get_secret_value()
             or settings.database_url.get_secret_value())
    if not value:
        raise RuntimeError('Set DATABASE_URL before running migrations')
    return value


async def run_online():
    engine = create_async_engine(database_url(), poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(configure)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    configure(config.attributes['connection'])
else:
    asyncio.run(run_online())
