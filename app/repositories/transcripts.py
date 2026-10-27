"""Idempotent transcript writes, serialized by the owning conversation row."""
from uuid import UUID

from sqlalchemy import select, func

from app.db.base import utcnow
from app.db.models import Conversation, ConversationMessage


async def save(database, conversation_id, owner, messages):
    async with database.sessions.begin() as session:
        conversation = await session.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.runtime_owner == owner,
            Conversation.status.in_(('connecting', 'active', 'reconnecting')),
            Conversation.lease_expires_at > utcnow(),
        ).with_for_update())
        if conversation is None:
            return False
        for values in messages:
            row = await session.get(ConversationMessage, values['id'])
            if row is None:
                session.add(ConversationMessage(**values))
            elif row.conversation_id == conversation_id and values['revision'] > row.revision:
                for key in ('text', 'state', 'revision', 'updated_at', 'completed_at'):
                    setattr(row, key, values[key])
        await session.flush()
        await metadata(session, conversation)
    return True


async def metadata(session, conversation, *, incomplete=False):
    belongs = ConversationMessage.conversation_id == conversation.id
    count, latest = (await session.execute(select(func.count(), func.max(ConversationMessage.updated_at)).where(belongs))).one()
    user = await session.scalar(select(ConversationMessage).where(
        belongs, ConversationMessage.role == 'user',
    ).order_by(ConversationMessage.sequence).limit(1))
    partial = await session.scalar(select(ConversationMessage.id).where(
        belongs, ConversationMessage.state == 'partial',
    ).limit(1))
    conversation.message_count = count
    conversation.has_user_message = user is not None
    conversation.title = ' '.join(user.text.split())[:120] if user else ''
    conversation.preview = ' '.join(user.text.split())[:240] if user else ''
    conversation.last_message_at = latest
    conversation.transcript_status = ('partial' if incomplete or partial is not None
                                      else 'available' if count else 'unavailable')


async def page(session, conversation_id: UUID, after: int, limit: int):
    return list((await session.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.sequence > after,
    ).order_by(ConversationMessage.sequence).limit(limit))).all())
