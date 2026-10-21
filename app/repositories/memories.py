"""Owner-scoped, bounded queries. Mutations serialize on the preferences row."""
from sqlalchemy import delete, select, update

from app.db.models import UserMemory, UserPreferences


async def locked_profile(session, user_id):
    if session.bind.dialect.name == 'sqlite':
        # SQLite ignores FOR UPDATE. Acquire its write lock before quota reads.
        await session.execute(update(UserPreferences).where(UserPreferences.user_id == user_id)
                              .values(memory_revision=UserPreferences.memory_revision))
    return await session.scalar(select(UserPreferences).where(
        UserPreferences.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))


async def list_owned(session, user_id):
    return list((await session.scalars(select(UserMemory).where(
        UserMemory.user_id == user_id,
    ).order_by(UserMemory.priority.desc(), UserMemory.created_at, UserMemory.id).limit(100))).all())


async def owned(session, user_id, memory_id):
    return await session.scalar(select(UserMemory).where(
        UserMemory.id == memory_id, UserMemory.user_id == user_id,
    ))


async def clear(session, user_id):
    return await session.execute(delete(UserMemory).where(UserMemory.user_id == user_id))
