from fastapi import APIRouter, Depends, Request

from app.api.dependencies import CurrentUser, get_database
from app.repositories import usage_limits
from app.schemas.usage import UsageStatus

router = APIRouter(prefix='/api/v1/usage', tags=['usage'])


@router.get('/me', response_model=UsageStatus)
async def my_usage(principal: CurrentUser, request: Request, database=Depends(get_database)):
    async with database.sessions() as session:
        return await usage_limits.status(session, principal.user.id, request.app.state.settings)
