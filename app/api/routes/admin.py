from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import CurrentUser, get_database
from app.core.errors import AppError
from app.db.base import utcnow
from app.repositories import usage_limits
from app.schemas.usage import AdminUsagePage, AdminUsageRow

router = APIRouter(prefix='/api/v1/admin', tags=['admin'])


@router.get('/operations')
async def operations(principal: CurrentUser, request: Request):
    if not principal.user.is_admin:
        raise AppError('admin_required', 403)
    registry = request.app.state.sessions
    return {**request.app.state.operations.snapshot(), 'active_sessions': len(registry.sessions),
            'draining': registry.draining, 'closing': registry.closing}


@router.post('/drain')
async def drain(principal: CurrentUser, request: Request):
    if not principal.user.is_admin:
        raise AppError('admin_required', 403)
    request.app.state.sessions.draining = True
    return {'draining': True, 'active_sessions': len(request.app.state.sessions.sessions)}


@router.get('/usage', response_model=AdminUsagePage)
async def usage(principal: CurrentUser, day: date | None = None,
                limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
                database=Depends(get_database)):
    if not principal.user.is_admin:
        raise AppError('admin_required', 403)
    async with database.sessions() as session:
        rows = await usage_limits.admin_daily(session, day or utcnow().date(), limit + 1, offset)
    return AdminUsagePage(
        items=[AdminUsageRow.model_validate(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )
