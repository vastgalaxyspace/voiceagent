import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.passwords import Passwords, token_digest
from app.db.base import utcnow
from app.db.models import AuthSession, User
from app.repositories import auth_sessions, users
from app.schemas.auth import LoginCredentials, RegistrationCredentials, TokenResponse


@dataclass(frozen=True)
class Principal:
    user: User
    session: AuthSession


async def register(database, passwords: Passwords, credentials: RegistrationCredentials) -> User:
    password_hash = await passwords.hash(credentials.password.get_secret_value())
    try:
        async with database.sessions.begin() as session:
            return await users.create(session, str(credentials.email), password_hash)
    except IntegrityError:
        raise AppError('account_already_exists', 409) from None


async def login(database, passwords: Passwords, credentials: LoginCredentials, hours: int) -> TokenResponse:
    async with database.sessions() as session:
        user = await users.by_email(session, str(credentials.email))
    # Hashing/verification never runs while holding a database connection.
    valid = await passwords.verify(credentials.password.get_secret_value(), user.password_hash if user else None)
    if not valid or user is None or not user.is_active:
        raise AppError('invalid_credentials', 401)
    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(hours=hours)
    async with database.sessions.begin() as session:
        session.add(AuthSession(token_hash=token_digest(token), user_id=user.id, expires_at=expires_at))
    return TokenResponse(access_token=token, expires_at=expires_at)


async def authenticate(database, token: str | None) -> Principal:
    if not token or not 32 <= len(token) <= 128:
        raise AppError('authentication_required', 401)
    async with database.sessions() as session:
        result = await auth_sessions.resolve(session, token_digest(token))
    if result is None:
        raise AppError('invalid_or_expired_session', 401)
    return Principal(user=result[0], session=result[1])
