"""Explicit user memory, consent, prompt budgets and revocable context manifests."""
import hashlib
import json
import re

from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import UserMemory
from app.repositories import memories as repository, users


def prompt_item(row):
    return {'key': row.key, 'content': row.content}


def content_hash(row):
    value = json.dumps(prompt_item(row), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def select_context(rows, settings):
    chosen, payload = [], []
    for row in rows:
        if len(chosen) >= settings.memory_prompt_max_items:
            break
        proposed = payload + [prompt_item(row)]
        encoded = json.dumps(proposed, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) <= settings.memory_prompt_max_bytes:
            chosen.append(row)
            payload = proposed
    return chosen


async def snapshot(session, profile, settings, goal=None):
    rows = await repository.list_owned(session, profile.user_id) if profile.memory_enabled else []
    terms = set(re.findall(r'\w+', (goal or profile.goal).lower())) - {'the', 'and', 'for', 'with', 'a', 'i', 'to', 'my'}
    if terms:
        rows.sort(key=lambda row: -len(terms.intersection(
            re.findall(r'\w+', (row.key + ' ' + row.content).lower()))))
    selected = select_context(rows, settings)
    # Historical conversation JSON holds identifiers and hashes, never fact text.
    return {
        'enabled': profile.memory_enabled, 'revision': profile.memory_revision,
        'items': [{'id': str(row.id), 'version': row.version, 'content_hash': content_hash(row)}
                  for row in selected],
    }


async def resolve(session, user_id, context, settings=None):
    if not context or not context.get('enabled'):
        return []
    profile = await repository.locked_profile(session, user_id)
    if not profile.memory_enabled or profile.memory_revision != context['revision']:
        raise AppError('conversation_memory_changed', 409)
    rows = {str(row.id): row for row in await repository.list_owned(session, user_id)}
    selected = []
    for item in context['items']:
        row = rows.get(item['id'])
        if row is None or row.version != item['version'] or content_hash(row) != item['content_hash']:
            raise AppError('conversation_memory_changed', 409)
        selected.append(row)
    if settings is not None and select_context(selected, settings) != selected:
        raise AppError('conversation_memory_budget_changed', 409)
    return [prompt_item(row) for row in selected]


async def list_owned(database, user_id):
    async with database.sessions() as session:
        profile = await users.preferences(session, user_id)
        return await repository.list_owned(session, user_id), profile.memory_enabled


async def get_owned(database, user_id, memory_id):
    async with database.sessions() as session:
        row = await repository.owned(session, user_id, memory_id)
        if row is None:
            raise AppError('memory_not_found', 404)
        return row


def changed(profile):
    profile.memory_revision += 1
    profile.updated_at = utcnow()


async def create(database, settings, user_id, body):
    try:
        async with database.sessions.begin() as session:
            profile = await repository.locked_profile(session, user_id)
            if not profile.memory_enabled:
                raise AppError('memory_not_enabled', 409)
            if len(await repository.list_owned(session, user_id)) >= settings.memory_max_items:
                raise AppError('memory_limit_reached', 409)
            row = UserMemory(user_id=user_id, **body.model_dump())
            session.add(row)
            changed(profile)
            await session.flush()
            return row
    except IntegrityError:
        raise AppError('memory_key_exists', 409) from None


async def replace(database, user_id, memory_id, body):
    async with database.sessions.begin() as session:
        profile = await repository.locked_profile(session, user_id)
        row = await repository.owned(session, user_id, memory_id)
        if row is None:
            raise AppError('memory_not_found', 404)
        if not profile.memory_enabled:
            raise AppError('memory_not_enabled', 409)
        if row.version != body.expected_version:
            raise AppError('memory_version_conflict', 409)
        row.content, row.priority = body.content, body.priority
        row.version += 1
        row.updated_at = utcnow()
        changed(profile)
        await session.flush()
        return row


async def forget(database, user_id, memory_id=None):
    async with database.sessions.begin() as session:
        profile = await repository.locked_profile(session, user_id)
        if memory_id is None:
            await repository.clear(session, user_id)
        else:
            row = await repository.owned(session, user_id, memory_id)
            if row is None:
                raise AppError('memory_not_found', 404)
            await session.delete(row)
        changed(profile)


async def update_preferences(database, user_id, values):
    async with database.sessions.begin() as session:
        profile = await repository.locked_profile(session, user_id)
        consent_changed = ('memory_enabled' in values and profile.memory_enabled != values['memory_enabled'])
        for key, value in values.items():
            setattr(profile, key, value)
        if consent_changed:
            changed(profile)
        profile.updated_at = utcnow()
        await session.flush()
        return profile, consent_changed
