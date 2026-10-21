from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageStatus(BaseModel):
    usage_date: date
    connected_seconds: float
    reserved_seconds: float
    available_seconds: float
    daily_connected_seconds: int
    estimated_cost_usd: Decimal
    reserved_cost_usd: Decimal
    daily_estimated_cost_limit_usd: Decimal | None
    cost_guard_enabled: bool
    sessions_started: int
    sessions_settled: int
    incomplete_cost_sessions: int
    resets_at: datetime


class AdminUsageRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    usage_date: date
    connected_seconds: Decimal
    reserved_seconds: Decimal
    estimated_cost_usd: Decimal
    reserved_cost_usd: Decimal
    sessions_started: int
    sessions_settled: int
    incomplete_cost_sessions: int
    updated_at: datetime


class AdminUsagePage(BaseModel):
    items: list[AdminUsageRow]
    next_offset: int | None
