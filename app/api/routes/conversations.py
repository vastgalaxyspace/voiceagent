from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import CurrentUser, get_database
from app.core.errors import AppError
from app.repositories import conversations as repository
from app.schemas.conversations import (ConversationCreate, ConversationPage, ConversationResponse,
                                      HistoryPage, HistoryItem, MessagePage, MessageResponse)
from app.services import conversations
from app.repositories import transcripts
from app.db.models import Conversation
from sqlalchemy import delete, select

router = APIRouter(prefix='/api/v1/conversations', tags=['conversations'])


@router.post('', response_model=ConversationResponse, status_code=201)
async def create(body: ConversationCreate, principal: CurrentUser, request: Request,
                 database=Depends(get_database)):
    return await conversations.create(database, request.app.state.settings, principal.user.id, body.goal,
                                      use_tools=body.use_tools)


@router.get('', response_model=ConversationPage | HistoryPage)
async def list_owned(principal: CurrentUser, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0, le=10000),
                     view: Literal['all', 'history'] = 'all', database=Depends(get_database)):
    async with database.sessions() as session:
        rows = await repository.list_owned(session, principal.user.id, limit + 1, offset, history=view == 'history')
    if view == 'history':
        return HistoryPage(items=[HistoryItem.model_validate(row) for row in rows[:limit]],
                           next_offset=offset + limit if len(rows) > limit else None)
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


@router.get('/{conversation_id}/messages', response_model=MessagePage)
async def messages(conversation_id: UUID, principal: CurrentUser,
                   after_sequence: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                   database=Depends(get_database)):
    async with database.sessions() as session:
        conversation = await repository.owned(session, principal.user.id, conversation_id)
        if conversation is None:
            raise AppError('conversation_not_found', 404)
        rows = await transcripts.page(session, conversation_id, after_sequence, limit + 1)
        return MessagePage(conversation_id=conversation_id, transcript_status=conversation.transcript_status,
                           items=[MessageResponse.model_validate(row) for row in rows[:limit]],
                           next_sequence=rows[limit - 1].sequence if len(rows) > limit else None)


@router.delete('/{conversation_id}', status_code=204)
async def delete_conversation(conversation_id: UUID, principal: CurrentUser, database=Depends(get_database)):
    async with database.sessions.begin() as session:
        conversation = await session.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == principal.user.id,
        ).with_for_update())
        if conversation is None:
            raise AppError('conversation_not_found', 404)
        if conversation.status not in ('ended', 'failed'):
            raise AppError('conversation_still_active', 409)
        await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    return Response(status_code=204)


@router.post('/{conversation_id}/stop', status_code=204)
async def stop(conversation_id: UUID, principal: CurrentUser, request: Request,
               database=Depends(get_database)):
    await request.app.state.sessions.request_stop(principal, conversation_id)
    return Response(status_code=204)
