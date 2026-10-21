from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import CurrentUser, get_database
from app.core.errors import AppError
from app.repositories import conversations as repository
from app.schemas.conversations import ConversationCreate, ConversationPage, ConversationResponse
from app.services import conversations

router = APIRouter(prefix='/api/v1/conversations', tags=['conversations'])


@router.post('', response_model=ConversationResponse, status_code=201)
async def create(body: ConversationCreate, principal: CurrentUser, request: Request,
                 database=Depends(get_database)):
    return await conversations.create(database, request.app.state.settings, principal.user.id, body.goal,
                                      use_tools=body.use_tools)


@router.get('', response_model=ConversationPage)
async def list_owned(principal: CurrentUser, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=10000), database=Depends(get_database)):
    async with database.sessions() as session:
        rows = await repository.list_owned(session, principal.user.id, limit + 1, offset)
    return ConversationPage(
        items=[ConversationResponse.model_validate(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get('/{conversation_id}', response_model=ConversationResponse)
async def get(conversation_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    return await conversations.get_owned(database, principal.user.id, conversation_id)


@router.get('/{conversation_id}/report')
async def report(conversation_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    conversation = await conversations.get_owned(database, principal.user.id, conversation_id)
    if conversation.report is None:
        raise AppError('report_not_available', 409)
    return conversation.report


@router.post('/{conversation_id}/stop', status_code=204)
async def stop(conversation_id: UUID, principal: CurrentUser, request: Request,
               database=Depends(get_database)):
    await request.app.state.sessions.request_stop(principal, conversation_id)
    return Response(status_code=204)
