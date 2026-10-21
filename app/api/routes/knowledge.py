from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import CurrentUser, get_database
from app.core.errors import AppError
from app.repositories import knowledge as repository
from app.schemas.knowledge import (KnowledgeCreate, KnowledgePage, KnowledgeResponse, KnowledgeSearch,
                                   KnowledgeSummary, KnowledgeUpdate, SharedKnowledgeCreate, SharedKnowledgeUpdate)
from app.services import knowledge

router = APIRouter(prefix='/api/v1/knowledge', tags=['knowledge'])
admin_router = APIRouter(prefix='/api/v1/admin/knowledge', tags=['admin knowledge'])


async def page(database, owner_id, limit, offset):
    async with database.sessions() as session:
        rows = await repository.list_owned(session, owner_id, limit + 1, offset)
    return KnowledgePage(items=[KnowledgeSummary.model_validate(row) for row in rows[:limit]],
                         next_offset=offset + limit if len(rows) > limit else None)


@router.get('/search', response_model=KnowledgeSearch)
async def search(principal: CurrentUser, q: str = Query(min_length=1, max_length=200),
                 limit: int = Query(3, ge=1, le=5), database=Depends(get_database)):
    async with database.sessions() as session:
        return KnowledgeSearch(items=await knowledge.search_in_session(session, principal.user.id, q, limit))


@router.get('/entries', response_model=KnowledgePage)
async def list_owned(principal: CurrentUser, limit: int = Query(20, ge=1, le=50),
                     offset: int = Query(0, ge=0, le=10000), database=Depends(get_database)):
    return await page(database, principal.user.id, limit, offset)


@router.post('/entries', response_model=KnowledgeResponse, status_code=201)
async def create(body: KnowledgeCreate, principal: CurrentUser, request: Request, database=Depends(get_database)):
    row = await knowledge.create(database, request.app.state.settings, principal, body)
    request.app.state.sessions.invalidate_knowledge(principal.user.id)
    return row


@router.get('/entries/{entry_id}', response_model=KnowledgeResponse)
async def get(entry_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    return await knowledge.get_accessible(database, principal.user.id, entry_id)


@router.put('/entries/{entry_id}', response_model=KnowledgeResponse)
async def replace(entry_id: UUID, body: KnowledgeUpdate, principal: CurrentUser, request: Request,
                  database=Depends(get_database)):
    row = await knowledge.replace(database, principal, entry_id, body)
    request.app.state.sessions.invalidate_knowledge(principal.user.id)
    return row


@router.delete('/entries/{entry_id}', status_code=204)
async def forget(entry_id: UUID, principal: CurrentUser, request: Request, database=Depends(get_database)):
    await knowledge.forget(database, principal, entry_id)
    request.app.state.sessions.invalidate_knowledge(principal.user.id)
    return Response(status_code=204)


@admin_router.get('', response_model=KnowledgePage)
async def list_shared(principal: CurrentUser, limit: int = Query(20, ge=1, le=50),
                      offset: int = Query(0, ge=0, le=10000), database=Depends(get_database)):
    if not principal.user.is_admin:
        raise AppError('admin_required', 403)
    return await page(database, None, limit, offset)


@admin_router.post('', response_model=KnowledgeResponse, status_code=201)
async def create_shared(body: SharedKnowledgeCreate, principal: CurrentUser, request: Request,
                        database=Depends(get_database)):
    row = await knowledge.create(database, request.app.state.settings, principal, body, shared=True)
    request.app.state.sessions.invalidate_knowledge()
    return row


@admin_router.get('/{entry_id}', response_model=KnowledgeResponse)
async def get_shared(entry_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    if not principal.user.is_admin:
        raise AppError('admin_required', 403)
    async with database.sessions() as session:
        row = await repository.owned(session, None, entry_id)
        if row is None:
            raise AppError('knowledge_not_found', 404)
        return row


@admin_router.put('/{entry_id}', response_model=KnowledgeResponse)
async def replace_shared(entry_id: UUID, body: SharedKnowledgeUpdate, principal: CurrentUser, request: Request,
                         database=Depends(get_database)):
    row = await knowledge.replace(database, principal, entry_id, body, shared=True)
    request.app.state.sessions.invalidate_knowledge()
    return row


@admin_router.delete('/{entry_id}', status_code=204)
async def forget_shared(entry_id: UUID, principal: CurrentUser, request: Request, database=Depends(get_database)):
    await knowledge.forget(database, principal, entry_id, shared=True)
    request.app.state.sessions.invalidate_knowledge()
    return Response(status_code=204)
