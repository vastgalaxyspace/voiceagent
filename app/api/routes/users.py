from fastapi import APIRouter, Depends, Request

from app.api.dependencies import CurrentUser, get_database
from app.repositories import users
from app.schemas.auth import UserResponse
from app.schemas.preferences import PreferencesPatch, PreferencesResponse
from app.services import memories

router = APIRouter(prefix='/api/v1/users/me', tags=['users'])


@router.get('', response_model=UserResponse)
async def me(principal: CurrentUser):
    return principal.user


@router.get('/preferences', response_model=PreferencesResponse)
async def preferences(principal: CurrentUser, database=Depends(get_database)):
    async with database.sessions() as session:
        return await users.preferences(session, principal.user.id)


@router.patch('/preferences', response_model=PreferencesResponse)
async def update_preferences(body: PreferencesPatch, principal: CurrentUser, request: Request,
                             database=Depends(get_database)):
    # Explicit nulls are ignored; an empty string deliberately clears the goal.
    values = body.model_dump(exclude_none=True, exclude_unset=True)
    profile, consent_changed = await memories.update_preferences(database, principal.user.id, values)
    if consent_changed:
        request.app.state.sessions.invalidate_memory(principal.user.id)
    return profile
