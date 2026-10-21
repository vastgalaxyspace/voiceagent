"""Application composition and ASGI entry point: app.main:app."""
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import router
from app.core.config import Settings
from app.core.errors import AppError
from app.core.passwords import Passwords
from app.core.paths import VOICE_CLIENT_ROOT
from app.core.security import TransportMiddleware, allowed_hosts
from app.services.operations import Operations
from app.integrations.gemini.live import GeminiProvider
from app.db.session import Database
from app.storage.reports import ReportStore
from app.services.session_registry import SessionRegistry


def create_app(settings: Settings | None = None, provider=None, database: Database | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        try:
            if settings.environment == 'production':
                async with asyncio.timeout(10):
                    if not await app.state.database.ready():
                        raise RuntimeError('Database migration is required before startup')
            await app.state.sessions.start()
            yield
        finally:
            await app.state.sessions.close()
            if app.state.database is not None:
                await app.state.database.close()

    app = FastAPI(title='Voice Agent Backend', version='0.8.0', lifespan=lifespan, redoc_url=None,
                  docs_url='/docs' if settings.enable_api_docs else None,
                  openapi_url='/openapi.json' if settings.enable_api_docs else None)
    app.state.operations = Operations()
    app.state.settings = settings
    app.state.active = False
    app.state.provider_injected = provider is not None
    app.state.provider = provider if provider is not None else GeminiProvider(settings)
    app.state.report_store = ReportStore(settings.reports_directory)
    app.state.database = database or (Database(settings) if settings.database_url.get_secret_value() else None)
    app.state.passwords = Passwords()
    app.state.auth_stop_events = {}
    app.state.sessions = SessionRegistry(app.state)

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        headers = {'WWW-Authenticate': 'Bearer'} if exc.status_code == 401 else None
        return JSONResponse({'error': exc.code}, status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default errors can echo passwords/tokens through their `input` field.
        errors = [{'loc': error['loc'], 'msg': error['msg'], 'type': error['type']}
                  for error in exc.errors()]
        return JSONResponse({'error': 'validation_error', 'details': errors}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({'error': 'database_unavailable'}, status_code=503)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(settings))
    app.add_middleware(TransportMiddleware, settings=settings, operations=app.state.operations)
    if settings.enable_test_harness:
        app.mount('/static', StaticFiles(directory=VOICE_CLIENT_ROOT), name='static')
    app.include_router(router)
    return app


app = create_app()
