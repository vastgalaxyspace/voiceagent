from uuid import UUID
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.db.base import utcnow
from app.db.models import Conversation
from app.repositories import usage_limits

LIVE_STATES = ('connecting', 'active', 'reconnecting')


async def owned(session: AsyncSession, user_id: UUID, conversation_id: UUID) -> Conversation | None:
    return await session.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id,
    ))


async def list_owned(session: AsyncSession, user_id: UUID, limit: int, offset: int):
    return list((await session.scalars(select(Conversation).options(defer(Conversation.report)).where(
        Conversation.user_id == user_id,
    ).order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit).offset(offset))).all())


async def claim(session: AsyncSession, user_id: UUID, conversation_id: UUID,
                runtime_owner: str, lease_seconds: float) -> Conversation | None:
    return await session.scalar(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id,
        Conversation.status == 'created',
    ).values(status='connecting', started_at=utcnow(), runtime_owner=runtime_owner,
             lease_expires_at=utcnow() + timedelta(seconds=lease_seconds)).returning(Conversation))


async def finish(session: AsyncSession, conversation_id: UUID, report: dict, runtime_owner: str):
    failed = report['end_reason'] in {
        'invalid_tool_call', 'tool_limit', 'tool_backpressure', 'tools_not_enabled',
        'tool_authorization_unavailable',
        'provider_error', 'provider_cleanup_error', 'io_or_setup_timeout',
        'provider_disconnected', 'server_cancelled',
        'runtime_lost', 'lease_lost', 'resume_unavailable', 'resume_rejected',
        'resume_attempts_exhausted', 'server_shutdown', 'cost_tracking_unavailable',
    }
    result = await session.scalar(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.status.in_(LIVE_STATES),
        Conversation.runtime_owner == runtime_owner, Conversation.lease_expires_at > utcnow(),
    ).values(status='failed' if failed else 'ended', ended_at=utcnow(),
             end_reason=report['end_reason'], report=report).returning(Conversation.id))
    if result is not None:
        return True
    # Retry after an uncertain commit may encounter the already-finalized row.
    row = await session.get(Conversation, conversation_id)
    return bool(row and row.runtime_owner == runtime_owner and row.status in ('ended', 'failed')
                and row.report and row.report.get('end_reason') == report['end_reason'])


async def renew(session: AsyncSession, conversation_id: UUID, owner: str, seconds: float):
    return await session.scalar(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.runtime_owner == owner,
        Conversation.status.in_(LIVE_STATES), Conversation.lease_expires_at > utcnow(),
    ).values(lease_expires_at=utcnow() + timedelta(seconds=seconds)).returning(Conversation.lease_expires_at))


async def transition(session: AsyncSession, conversation_id: UUID, owner: str, status: str):
    assert status in LIVE_STATES
    return await session.scalar(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.runtime_owner == owner,
        Conversation.status.in_(LIVE_STATES), Conversation.lease_expires_at > utcnow(),
    ).values(status=status).returning(Conversation.id))


async def recover_expired(session: AsyncSession) -> int:
    now = utcnow()
    ids = list((await session.scalars(select(Conversation.id).where(
        Conversation.status.in_(LIVE_STATES), Conversation.lease_expires_at <= now,
    ).order_by(Conversation.lease_expires_at).limit(100).with_for_update(skip_locked=True))).all())
    count = 0
    for conversation_id in ids:
        result = await session.execute(update(Conversation).where(
            Conversation.id == conversation_id, Conversation.status.in_(LIVE_STATES),
            Conversation.lease_expires_at <= now,
        ).values(status='failed', ended_at=now, end_reason='runtime_lost', report={
            'session_id': str(conversation_id), 'end_reason': 'runtime_lost',
            'recovered': True, 'usage_complete': False, 'estimated_model_cost_usd': None,
        }))
        if result.rowcount:
            await usage_limits.settle(session, conversation_id, None, None, False, conservative=True)
        count += result.rowcount
    return count


async def cancel_created(session: AsyncSession, user_id: UUID, conversation_id: UUID):
    return await session.scalar(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id,
        Conversation.status == 'created',
    ).values(status='ended', ended_at=utcnow(), end_reason='user_stopped').returning(Conversation.id))
