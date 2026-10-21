from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import User, UserPreferences


async def by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def create(session: AsyncSession, email: str, password_hash: str) -> User:
    user = User(email=email, password_hash=password_hash)
    session.add(user)
    await session.flush()
    session.add(UserPreferences(user_id=user.id))
    await session.flush()
    return user


async def preferences(session: AsyncSession, user_id: UUID) -> UserPreferences:
    return await session.get(UserPreferences, user_id)


async def update_preferences(session: AsyncSession, user_id: UUID, values: dict) -> UserPreferences:
    return await session.scalar(update(UserPreferences).where(
        UserPreferences.user_id == user_id,
    ).values(**values, updated_at=utcnow()).returning(UserPreferences))
