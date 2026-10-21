"""Serve the temporary voice test harness; this is not the Kotlin application."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.core.paths import VOICE_CLIENT_ROOT

router = APIRouter()


@router.get('/')
async def index(request: Request):
    if not request.app.state.settings.enable_test_harness:
        raise HTTPException(404)
    return FileResponse(VOICE_CLIENT_ROOT / 'index.html')
