from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.services.auth import Principal, authenticate

bearer = HTTPBearer(auto_error=False)


def get_database(request: Request):
    if request.app.state.database is None:
        raise AppError('database_not_configured', 503)
    return request.app.state.database


async def get_principal(
    database=Depends(get_database),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    return await authenticate(database, credentials.credentials if credentials else None)


CurrentUser = Annotated[Principal, Depends(get_principal)]
