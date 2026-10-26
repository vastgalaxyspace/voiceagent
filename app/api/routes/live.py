"""Authenticate each socket attachment; runtimes survive brief client disconnects."""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.core.security import websocket_allowed
from app.schemas.live import AuthenticatedStart
from app.services import auth, conversations

router = APIRouter()


@router.websocket('/ws/live')
async def live(ws: WebSocket):
    state = ws.app.state
    if not websocket_allowed(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    managed = None
    try:
        try:
            async with asyncio.timeout(5):
                raw = await ws.receive_text()
                if len(raw) > 4096:
                    raise ValueError('oversized start')
                start = AuthenticatedStart.model_validate_json(raw)
        except (ValueError, KeyError, TimeoutError):
            raise AppError('invalid_start') from None
        if state.database is None:
            raise AppError('database_not_configured', 503)
        header = ws.headers.get('authorization')
        if header:
            scheme, _, token = header.partition(' ')
            if scheme.lower() != 'bearer':
                raise AppError('authentication_required', 401)
        else:
            token = start.access_token.get_secret_value() if start.access_token else None
        principal = await auth.authenticate(state.database, token)
        await conversations.get_owned(state.database, principal.user.id, start.conversation_id)
        managed = await state.sessions.attach(ws, principal, start.conversation_id, token,
                                              speech_detection=start.speech_detection)
        await state.sessions.serve(ws, managed)
    except AppError as exc:
        try:
            await ws.send_json({'type': 'error', 'code': exc.code})
        except Exception:
            pass
    except SQLAlchemyError:
        try:
            await ws.send_json({'type': 'error', 'code': 'database_unavailable'})
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    finally:
        if managed is None:
            try:
                async with asyncio.timeout(state.settings.io_timeout_seconds):
                    await ws.close()
            except Exception:
                pass
