"""Authenticated knowledge management and bounded lexical retrieval."""
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import KnowledgeEntry
from app.repositories import knowledge as repository, memories, users


async def context(session, user_id):
    profile = await users.preferences(session, user_id)
    shared = await repository.state(session)
    if profile is None or shared is None:
        raise AppError('knowledge_not_configured', 503)
    return {'private_revision': profile.knowledge_revision, 'shared_revision': shared.revision}


async def valid(session, user_id, expected):
    return bool(expected is not None and await context(session, user_id) == expected)


async def lock_owner(session, owner_id):
    if owner_id is None:
        shared = await repository.state(session, lock=True)
        if shared is None:
            raise AppError('knowledge_not_configured', 503)
        return shared
    return await memories.locked_profile(session, owner_id)


def changed(row, owner_id):
    if owner_id is None:
        row.revision += 1
    else:
        row.knowledge_revision += 1
        row.updated_at = utcnow()


async def create(database, settings, principal, body, *, shared=False):
    if shared and not principal.user.is_admin:
        raise AppError('admin_required', 403)
    owner_id = None if shared else principal.user.id
    async with database.sessions.begin() as session:
        owner = await lock_owner(session, owner_id)
        limit = settings.knowledge_max_shared_entries if shared else settings.knowledge_max_private_entries
        if await repository.count_owned(session, owner_id) >= limit:
            raise AppError('knowledge_limit_reached', 409)
        row = KnowledgeEntry(owner_id=owner_id, **body.model_dump())
        session.add(row)
        changed(owner, owner_id)
        await session.flush()
        return row


async def replace(database, principal, entry_id, body, *, shared=False):
    if shared and not principal.user.is_admin:
        raise AppError('admin_required', 403)
    owner_id = None if shared else principal.user.id
    async with database.sessions.begin() as session:
        owner = await lock_owner(session, owner_id)
        row = await repository.owned(session, owner_id, entry_id)
        if row is None:
            raise AppError('knowledge_not_found', 404)
        if row.version != body.expected_version:
            raise AppError('knowledge_version_conflict', 409)
        for key, value in body.model_dump(exclude={'expected_version'}).items():
            setattr(row, key, value)
        row.version += 1
        row.updated_at = utcnow()
        changed(owner, owner_id)
        await session.flush()
        return row


async def forget(database, principal, entry_id, *, shared=False):
    if shared and not principal.user.is_admin:
        raise AppError('admin_required', 403)
    owner_id = None if shared else principal.user.id
    async with database.sessions.begin() as session:
        owner = await lock_owner(session, owner_id)
        row = await repository.owned(session, owner_id, entry_id)
        if row is None:
            raise AppError('knowledge_not_found', 404)
        await session.delete(row)
        changed(owner, owner_id)


def normalize_query(query):
    query = ' '.join(query.split())
    if not query or '\x00' in query or len(query) > 200 or len(query.split()) > 8:
        raise AppError('invalid_knowledge_query', 422)
    return query


async def search_in_session(session, user_id, query, limit=3):
    query = normalize_query(query)
    rows = await repository.search(session, user_id, query, min(5, limit))
    hits = []
    for row in rows:
        positions = [row.content.lower().find(word.lower()) for word in query.split()]
        positions = [position for position in positions if position >= 0]
        offset = max(0, min(positions) - 80) if positions else 0
        hits.append({'id': str(row.id), 'title': row.title, 'source_url': row.source_url,
                     'version': row.version, 'excerpt': row.content[offset:offset + 320], 'offset': offset})
    return hits


async def get_accessible(database, user_id, entry_id):
    async with database.sessions() as session:
        row = await repository.accessible(session, user_id, entry_id)
        if row is None:
            raise AppError('knowledge_not_found', 404)
        return row
