import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get('/health')
async def health(request: Request):
    settings = request.app.state.settings
    return {
        'status': 'ok', 'phase': 8,
        'configured': bool(settings.gemini_api_key.get_secret_value()),
        'model': settings.gemini_model,
        'active_session': request.app.state.active,
        'database_configured': request.app.state.database is not None,
    }


@router.get('/health/ready')
async def ready(request: Request):
    try:
        database = request.app.state.database
        if request.app.state.sessions.draining or request.app.state.sessions.closing:
            return JSONResponse({'status': 'not_ready', 'error': 'server_draining'}, status_code=503)
        async with asyncio.timeout(5):
            if database is not None and await database.ready():
                return {'status': 'ready', 'phase': 8}
    except Exception:
        pass
    return JSONResponse({'status': 'not_ready', 'error': 'database_or_migrations_unavailable'}, status_code=503)
