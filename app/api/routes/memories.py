from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import CurrentUser, get_database
from app.schemas.memory import MemoryCreate, MemoryList, MemoryResponse, MemoryUpdate
from app.services import memories

router = APIRouter(prefix='/api/v1/users/me/memories', tags=['memory'])


@router.get('', response_model=MemoryList)
async def list_owned(principal: CurrentUser, request: Request, database=Depends(get_database)):
    rows, enabled = await memories.list_owned(database, principal.user.id)
    return MemoryList(items=rows, memory_enabled=enabled, limit=request.app.state.settings.memory_max_items)


@router.post('', response_model=MemoryResponse, status_code=201)
async def create(body: MemoryCreate, principal: CurrentUser, request: Request, database=Depends(get_database)):
    row = await memories.create(database, request.app.state.settings, principal.user.id, body)
    request.app.state.sessions.invalidate_memory(principal.user.id)
    return row


@router.put('/{memory_id}', response_model=MemoryResponse)
async def replace(memory_id: UUID, body: MemoryUpdate, principal: CurrentUser, request: Request,
                  database=Depends(get_database)):
    row = await memories.replace(database, principal.user.id, memory_id, body)
    request.app.state.sessions.invalidate_memory(principal.user.id)
    return row


@router.get('/{memory_id}', response_model=MemoryResponse)
async def get_owned(memory_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    return await memories.get_owned(database, principal.user.id, memory_id)


@router.delete('', status_code=204)
async def forget_all(principal: CurrentUser, request: Request, database=Depends(get_database)):
    await memories.forget(database, principal.user.id)
    request.app.state.sessions.invalidate_memory(principal.user.id)
    return Response(status_code=204)


@router.delete('/{memory_id}', status_code=204)
async def forget_one(memory_id: UUID, principal: CurrentUser, request: Request, database=Depends(get_database)):
    await memories.forget(database, principal.user.id, memory_id)
    request.app.state.sessions.invalidate_memory(principal.user.id)
    return Response(status_code=204)
