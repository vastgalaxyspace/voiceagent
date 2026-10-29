"""Owner-checked, bounded historical context; never replays historical audio."""
import hashlib
import json

from sqlalchemy import select, update

from app.db.models import Conversation, ConversationMessage


def payload(messages):
    return [{'sequence': m.sequence, 'revision': m.revision, 'role': m.role,
             'state': m.state, 'text': m.text} for m in messages]


def digest(messages):
    return hashlib.sha256(json.dumps(payload(messages), ensure_ascii=False,
                                    sort_keys=True).encode()).hexdigest()


async def load_context(database, user_id, parent_id, max_bytes):
    result = {'sessions': [], 'truncated': False}
    if parent_id is None:
        return None
    async with database.sessions() as session:
        seen = set()
        while parent_id and len(seen) < 8:
            if parent_id in seen:
                result['truncated'] = True
                break
            seen.add(parent_id)
            row = await session.scalar(select(Conversation).where(
                Conversation.id == parent_id, Conversation.user_id == user_id,
                Conversation.status.in_(('ended', 'failed'))))
            if row is None:
                break  # Deleted/foreign history must never be loaded.
            messages = list((await session.scalars(select(ConversationMessage).where(
                ConversationMessage.conversation_id == row.id,
            ).order_by(ConversationMessage.sequence.desc()).limit(512))).all())
            messages.reverse()
            # Summary is only trusted while covered rows have not changed since publication.
            use_summary = bool(row.summary and row.summary_through_sequence and all(
                m.updated_at <= row.ended_at for m in messages
                if m.sequence <= row.summary_through_sequence))
            item = {'summary': row.summary if use_summary else '',
                    'messages': [], 'history_status': row.transcript_status}
            result['sessions'].insert(0, item)
            if len(json.dumps(result, ensure_ascii=False).encode()) > max_bytes:
                result['sessions'].pop(0)
                result['truncated'] = True
                break
            recent = [m for m in messages if not use_summary or m.sequence > row.summary_through_sequence]
            for message in reversed(recent):
                item['messages'].insert(0, {'role': message.role, 'text': message.text,
                                            'state': message.state})
                if len(json.dumps(result, ensure_ascii=False).encode()) > max_bytes:
                    item['messages'].pop(0)
                    result['truncated'] = True
                    break
            parent_id = row.continued_from_id
        if parent_id and len(seen) >= 8:
            result['truncated'] = True
    return result


async def summarize_one(database, settings, generate):
    """Retryable scan of unsummarized terminal sessions. CAS prevents stale writes.

    Run one worker per deployment to avoid duplicate paid generation. Database
    state is the durable queue: a failed generation remains eligible next run.
    """
    async with database.sessions() as session:
        candidates = list((await session.scalars(select(Conversation).where(
            Conversation.status.in_(('ended', 'failed')), Conversation.summary_version == 0,
            Conversation.message_count >= settings.summary_min_messages,
        ).order_by(Conversation.ended_at, Conversation.id).limit(20))).all())
        for row in candidates:
            messages = list((await session.scalars(select(ConversationMessage).where(
                ConversationMessage.conversation_id == row.id,
            ).order_by(ConversationMessage.sequence).limit(512))).all())
            if not messages:
                continue
            # Summarize an exact prefix, leaving the rest for a future continuation.
            chosen = []
            for message in messages:
                if len(json.dumps(payload(chosen + [message]), ensure_ascii=False).encode()) > 48000:
                    break
                chosen.append(message)
            if not chosen:
                continue
            conversation_id, owner = row.id, row.user_id
            expected, through = digest(chosen), chosen[-1].sequence
            transcript = payload(chosen)
            break
        else:
            return False
    summary = await generate(transcript)
    if not isinstance(summary, str) or not summary.strip() or len(summary.encode()) > 4000:
        raise ValueError('Summary is empty or exceeds 4000 UTF-8 bytes')
    async with database.sessions.begin() as session:
        current = list((await session.scalars(select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.sequence <= through,
        ).order_by(ConversationMessage.sequence))).all())
        if digest(current) != expected:
            return False
        await session.execute(update(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == owner,
            Conversation.status.in_(('ended', 'failed')), Conversation.summary_version == 0,
        ).values(summary=summary.strip(), summary_through_sequence=through, summary_version=1))
    return True
