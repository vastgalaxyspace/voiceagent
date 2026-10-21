from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import AuthSession, User


async def resolve(session: AsyncSession, digest: str):
    return (await session.execute(select(User, AuthSession).join(
        AuthSession, AuthSession.user_id == User.id,
    ).where(
        AuthSession.token_hash == digest, AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > utcnow(), User.is_active.is_(True),
    ))).one_or_none()


async def revoke(session: AsyncSession, digest: str):
    await session.execute(update(AuthSession).where(
        AuthSession.token_hash == digest, AuthSession.revoked_at.is_(None),
    ).values(revoked_at=utcnow()))
