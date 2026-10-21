"""Atomic allowance reservation, idempotent settlement and usage summaries."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import ConversationRateWindow, DailyUsage, UsageReservation

SECONDS = Decimal('0.001')
USD = Decimal('0.00000001')


@dataclass(frozen=True)
class Allocation:
    seconds: float
    cost_usd: Decimal


def _insert(session: AsyncSession, model):
    dialect = session.bind.dialect.name
    return (pg_insert(model) if dialect == 'postgresql' else sqlite_insert(model))


def utc_day():
    return utcnow().date()


async def consume_creation(session: AsyncSession, user_id: UUID, limit: int):
    now = utcnow()
    window = now.replace(minute=0, second=0, microsecond=0)
    statement = _insert(session, ConversationRateWindow).values(
        user_id=user_id, window_start=window, count=0,
    ).on_conflict_do_nothing(index_elements=['user_id', 'window_start'])
    await session.execute(statement)
    accepted = await session.scalar(update(ConversationRateWindow).where(
        ConversationRateWindow.user_id == user_id,
        ConversationRateWindow.window_start == window,
        ConversationRateWindow.count < limit,
    ).values(count=ConversationRateWindow.count + 1).returning(ConversationRateWindow.count))
    if accepted is None:
        raise AppError('conversation_rate_limited', 429)


async def _locked_daily(session: AsyncSession, user_id: UUID, usage_date):
    statement = _insert(session, DailyUsage).values(
        user_id=user_id, usage_date=usage_date, updated_at=utcnow(),
    ).on_conflict_do_nothing(index_elements=['user_id', 'usage_date'])
    await session.execute(statement)
    return await session.scalar(select(DailyUsage).where(
        DailyUsage.user_id == user_id, DailyUsage.usage_date == usage_date,
    ).with_for_update())


async def reserve(session: AsyncSession, user_id: UUID, conversation_id: UUID, settings) -> Allocation:
    usage_date = utc_day()
    daily = await _locked_daily(session, user_id, usage_date)
    available = (Decimal(settings.daily_connected_seconds) - daily.connected_seconds
                 - daily.reserved_seconds)
    seconds = min(Decimal(str(settings.session_max_seconds)), available).quantize(SECONDS)
    if seconds < Decimal(str(settings.minimum_session_seconds)):
        raise AppError('daily_allowance_exhausted', 429)

    cost = Decimal('0')
    if settings.cost_guard_enabled:
        cost = Decimal(settings.session_estimated_cost_limit_usd).quantize(USD)
        cost_available = (Decimal(settings.daily_estimated_cost_limit_usd)
                          - daily.estimated_cost_usd - daily.reserved_cost_usd)
        if cost_available < cost:
            raise AppError('daily_cost_limit_reached', 429)

    reservation = UsageReservation(
        conversation_id=conversation_id, user_id=user_id, usage_date=usage_date,
        reserved_seconds=seconds, reserved_cost_usd=cost, status='reserved', created_at=utcnow(),
    )
    session.add(reservation)
    daily.reserved_seconds += seconds
    daily.reserved_cost_usd += cost
    daily.sessions_started += 1
    daily.updated_at = utcnow()
    await session.flush()
    return Allocation(float(seconds), cost)


async def settle(session: AsyncSession, conversation_id: UUID, duration_seconds: float | None,
                 estimated_cost_usd: float | None, cost_complete: bool, *, conservative=False):
    probe = await session.get(UsageReservation, conversation_id)
    if probe is None:
        return None
    daily = await _locked_daily(session, probe.user_id, probe.usage_date)
    reservation = await session.scalar(select(UsageReservation).where(
        UsageReservation.conversation_id == conversation_id,
    ).with_for_update().execution_options(populate_existing=True))
    if reservation.status == 'settled':
        return reservation

    if conservative or duration_seconds is None:
        charged_seconds = reservation.reserved_seconds
    else:
        value = Decimal(str(max(0, duration_seconds))).quantize(SECONDS, rounding=ROUND_HALF_UP)
        charged_seconds = min(value, reservation.reserved_seconds)
    if reservation.reserved_cost_usd and (not cost_complete or estimated_cost_usd is None):
        charged_cost = reservation.reserved_cost_usd
        complete = False
    else:
        charged_cost = Decimal(str(max(0, estimated_cost_usd or 0))).quantize(USD, rounding=ROUND_HALF_UP)
        complete = bool(cost_complete)

    daily.reserved_seconds -= reservation.reserved_seconds
    daily.reserved_cost_usd -= reservation.reserved_cost_usd
    daily.connected_seconds += charged_seconds
    daily.estimated_cost_usd += charged_cost
    daily.sessions_settled += 1
    daily.incomplete_cost_sessions += 0 if complete else 1
    daily.updated_at = utcnow()
    reservation.status = 'settled'
    reservation.settled_seconds = charged_seconds
    reservation.settled_cost_usd = charged_cost
    reservation.cost_complete = complete
    reservation.settled_at = utcnow()
    await session.flush()
    return reservation


async def status(session: AsyncSession, user_id: UUID, settings):
    usage_date = utc_day()
    row = await session.get(DailyUsage, (user_id, usage_date))
    connected = row.connected_seconds if row else Decimal('0')
    reserved = row.reserved_seconds if row else Decimal('0')
    cost = row.estimated_cost_usd if row else Decimal('0')
    reserved_cost = row.reserved_cost_usd if row else Decimal('0')
    tomorrow = datetime.combine(usage_date + timedelta(days=1), time.min, timezone.utc)
    return {
        'usage_date': usage_date, 'connected_seconds': float(connected),
        'reserved_seconds': float(reserved),
        'available_seconds': float(max(Decimal('0'), Decimal(settings.daily_connected_seconds) - connected - reserved)),
        'daily_connected_seconds': settings.daily_connected_seconds,
        'estimated_cost_usd': cost, 'reserved_cost_usd': reserved_cost,
        'daily_estimated_cost_limit_usd': (settings.daily_estimated_cost_limit_usd
                                           if settings.cost_guard_enabled else None),
        'cost_guard_enabled': settings.cost_guard_enabled,
        'sessions_started': row.sessions_started if row else 0,
        'sessions_settled': row.sessions_settled if row else 0,
        'incomplete_cost_sessions': row.incomplete_cost_sessions if row else 0,
        'resets_at': tomorrow,
    }


async def admin_daily(session: AsyncSession, usage_date, limit: int, offset: int):
    return list((await session.scalars(select(DailyUsage).where(
        DailyUsage.usage_date == usage_date,
    ).order_by(DailyUsage.estimated_cost_usd.desc(), DailyUsage.user_id).limit(limit).offset(offset))).all())
