from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptVersion


async def get(session: AsyncSession, version: str) -> PromptVersion | None:
    return await session.get(PromptVersion, version)
