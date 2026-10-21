from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import CurrentUser, get_database
from app.repositories import auth_sessions
from app.schemas.auth import Credentials, TokenResponse, UserResponse
from app.services import auth
from app.core.errors import AppError

router = APIRouter(prefix='/api/v1/auth', tags=['auth'])


@router.post('/register', response_model=UserResponse, status_code=201)
async def register(body: Credentials, request: Request, database=Depends(get_database)):
    if not request.app.state.settings.registration_enabled:
        raise AppError('registration_disabled', 403)
    return await auth.register(database, request.app.state.passwords, body)


@router.post('/login', response_model=TokenResponse)
async def login(body: Credentials, request: Request, database=Depends(get_database)):
    return await auth.login(database, request.app.state.passwords, body,
                            request.app.state.settings.auth_session_hours)


@router.post('/logout', status_code=204)
async def logout(principal: CurrentUser, request: Request, database=Depends(get_database)):
    async with database.sessions.begin() as session:
        await auth_sessions.revoke(session, principal.session.token_hash)
    for event in request.app.state.auth_stop_events.get(principal.session.token_hash, set()):
        event.set()
    return Response(status_code=204)
