from sqlalchemy import and_, func, literal_column, or_, select, update
from sqlalchemy.orm import defer

from app.db.models import KnowledgeEntry, KnowledgeState, knowledge_vector


def visible(user_id):
    return or_(KnowledgeEntry.owner_id == user_id,
               and_(KnowledgeEntry.owner_id.is_(None), KnowledgeEntry.published.is_(True)))


async def state(session, *, lock=False):
    if lock and session.bind.dialect.name == 'sqlite':
        await session.execute(update(KnowledgeState).where(KnowledgeState.id == 1)
                              .values(revision=KnowledgeState.revision))
    statement = select(KnowledgeState).where(KnowledgeState.id == 1)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(statement)


async def list_owned(session, owner_id, limit, offset):
    return list((await session.scalars(select(KnowledgeEntry).options(defer(KnowledgeEntry.content)).where(
        KnowledgeEntry.owner_id == owner_id,
    ).order_by(KnowledgeEntry.updated_at.desc(), KnowledgeEntry.id).limit(limit).offset(offset))).all())


async def count_owned(session, owner_id):
    return await session.scalar(select(func.count()).select_from(KnowledgeEntry).where(
        KnowledgeEntry.owner_id == owner_id,
    ))


async def owned(session, owner_id, entry_id):
    return await session.scalar(select(KnowledgeEntry).where(
        KnowledgeEntry.id == entry_id, KnowledgeEntry.owner_id == owner_id,
    ))


async def accessible(session, user_id, entry_id):
    return await session.scalar(select(KnowledgeEntry).where(
        KnowledgeEntry.id == entry_id, visible(user_id),
    ))


async def search(session, user_id, query, limit):
    statement = select(KnowledgeEntry).where(visible(user_id))
    if session.bind.dialect.name == 'postgresql':
        vector = knowledge_vector()
        terms = func.plainto_tsquery(literal_column("'simple'::regconfig"), query)
        statement = statement.where(vector.op('@@')(terms)).order_by(
            func.ts_rank_cd(vector, terms).desc(), KnowledgeEntry.updated_at.desc(), KnowledgeEntry.id)
    else:
        # Deterministic lexical fallback for SQLite tests, not semantic search.
        text = func.lower(KnowledgeEntry.title + ' ' + KnowledgeEntry.content)
        for word in query.lower().split():
            statement = statement.where(text.contains(word, autoescape=True))
        statement = statement.order_by(KnowledgeEntry.updated_at.desc(), KnowledgeEntry.id)
    return list((await session.scalars(statement.limit(limit))).all())
