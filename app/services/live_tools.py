"""Bounded read-only tool execution, with server-bound identity and no raw logs."""
import asyncio
import hashlib
import json
from time import monotonic
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import Conversation, UserPreferences
from app.repositories import auth_sessions, knowledge as repository, usage_limits
from app.schemas.knowledge import EmptyToolArgs, ReadKnowledgeArgs, SearchKnowledgeArgs
from app.services import knowledge

ARGUMENTS = {'search_knowledge': SearchKnowledgeArgs, 'get_knowledge_entry': ReadKnowledgeArgs,
             'get_usage_allowance': EmptyToolArgs}


class ToolSessionEnd(Exception):
    def __init__(self, reason):
        self.reason = reason


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def error(code):
    return {'ok': False, 'error': code}


class ToolSession:
    def __init__(self, database, policy, principal, conversation, owner, measurements, max_seconds):
        self.database, self.policy, self.principal = database, policy, principal
        self.conversation, self.owner = conversation, owner
        self.measurements, self.max_seconds = measurements, max_seconds
        self.seen, self.cache, self.cancelled = {}, {}, set()

    def accept(self, call):
        if (not isinstance(call.id, str) or not call.id or len(call.id) > 128 or '\x00' in call.id
                or not isinstance(call.name, str) or not call.name or len(call.name) > 64
                or call.will_continue or call.partial_args):
            raise ToolSessionEnd('invalid_tool_call')
        if call.args is not None and not isinstance(call.args, dict):
            raise ToolSessionEnd('invalid_tool_call')
        try:
            raw = encoded({'name': call.name, 'args': call.args or {}})
        except (ValueError, TypeError, UnicodeError):
            raise ToolSessionEnd('invalid_tool_call') from None
        if len(raw) > 2048:
            raise ToolSessionEnd('invalid_tool_call')
        if self.measurements.tool_call_count >= self.policy.tool_max_calls:
            raise ToolSessionEnd('tool_limit')
        self.measurements.tool_call_count += 1
        signature = hashlib.sha256(raw).digest()
        if call.id in self.seen and self.seen[call.id] != signature:
            raise ToolSessionEnd('invalid_tool_call')
        self.seen[call.id] = signature
        return call.id not in self.cancelled

    async def authorize(self):
        if not self.policy.live_tools_enabled:
            raise ToolSessionEnd('tools_disabled')
        try:
            async with self.database.sessions() as session:
                identity = await auth_sessions.resolve(session, self.principal.session.token_hash)
                if identity is None or identity[0].id != self.principal.user.id:
                    raise ToolSessionEnd('auth_revoked')
                active = await session.scalar(select(Conversation.id).where(
                    Conversation.id == self.conversation.id, Conversation.runtime_owner == self.owner,
                    Conversation.status.in_(('connecting', 'active', 'reconnecting')),
                    Conversation.lease_expires_at > utcnow(),
                ))
                if active is None:
                    raise ToolSessionEnd('lease_lost')
                profile = await session.get(UserPreferences, self.principal.user.id)
                if profile is None:
                    raise ToolSessionEnd('auth_revoked')
                memory = self.conversation.preferences_snapshot.get('memory_context', {})
                if memory.get('enabled') and (not profile.memory_enabled or profile.memory_revision != memory['revision']):
                    raise ToolSessionEnd('memory_changed')
                shared = await repository.state(session)
                expected = self.conversation.preferences_snapshot.get('knowledge_context')
                current = {'private_revision': profile.knowledge_revision, 'shared_revision': shared.revision} if shared else None
                if expected is None or current != expected:
                    raise ToolSessionEnd('knowledge_changed')
        except SQLAlchemyError:
            raise ToolSessionEnd('tool_authorization_unavailable') from None

    async def execute(self, call):
        schema = ARGUMENTS.get(call.name)
        if schema is None:
            return error('tool_not_allowed')
        try:
            args = schema.model_validate(call.args or {})
        except (ValidationError, ValueError):
            return error('invalid_tool_arguments')
        async with self.database.sessions() as session:
            if call.name == 'search_knowledge':
                items = await knowledge.search_in_session(session, self.principal.user.id, args.query, args.limit)
                result = {'ok': True, 'untrusted_reference_data': True, 'items': items, 'truncated': False}
                while items and len(encoded(result)) > self.policy.tool_result_max_bytes:
                    items.pop()
                    result['truncated'] = True
                self.measurements.knowledge_result_count += len(items)
                return result
            if call.name == 'get_knowledge_entry':
                row = await repository.accessible(session, self.principal.user.id, UUID(args.entry_id))
                if row is None:
                    return error('knowledge_not_found')
                if row.version != args.expected_version:
                    return error('knowledge_version_changed')
                count = args.max_chars
                while count:
                    excerpt = row.content[args.offset:args.offset + count]
                    end = args.offset + len(excerpt)
                    result = {'ok': True, 'untrusted_reference_data': True, 'id': str(row.id), 'title': row.title,
                              'source_url': row.source_url, 'version': row.version, 'excerpt': excerpt,
                              'offset': args.offset, 'next_offset': end if end < len(row.content) else None}
                    if len(encoded(result)) <= self.policy.tool_result_max_bytes:
                        self.measurements.knowledge_result_count += 1
                        return result
                    count //= 2
                return error('tool_result_too_large')
            status = await usage_limits.status(session, self.principal.user.id, self.policy)
            return {'ok': True, 'available_daily_seconds': status['available_seconds'],
                    'reserved_daily_seconds': status['reserved_seconds'],
                    'remaining_session_seconds': round(max(0, self.max_seconds - (monotonic() - self.measurements.started)), 3),
                    'resets_at': status['resets_at'].isoformat()}

    def clear(self):
        self.seen.clear()
        self.cache.clear()
        self.cancelled.clear()


class ToolConnection:
    """One worker per provider connection; receiving audio never waits for a tool."""
    def __init__(self, session, connection, outbox):
        self.session, self.connection, self.outbox = session, connection, outbox
        self.queue = asyncio.Queue(maxsize=4)
        self.pending = set()
        self.active_id = self.active = None

    def submit(self, calls):
        if not calls or len(calls) > 4:
            raise ToolSessionEnd('invalid_tool_call')
        for call in calls:
            if not self.session.accept(call) or call.id in self.pending:
                continue
            if len(self.pending) >= 4:
                raise ToolSessionEnd('tool_backpressure')
            self.pending.add(call.id)
            self.queue.put_nowait(call)

    def cancel(self, ids):
        for identifier in ids or []:
            if identifier in self.pending and identifier not in self.session.cancelled:
                self.session.cancelled.add(identifier)
                self.session.measurements.tool_cancelled_count += 1
                if self.active_id == identifier and self.active is not None:
                    self.active.cancel()

    async def respond(self, call):
        try:
            async with asyncio.timeout(self.session.policy.tool_timeout_seconds):
                await self.session.authorize()
                result = self.session.cache.get(call.id)
                if result is None:
                    result = await self.session.execute(call)
        except TimeoutError:
            result = error('tool_timeout')
        except AppError as exc:
            result = error(exc.code)
        except SQLAlchemyError:
            result = error('tool_unavailable')
        if len(encoded(result)) > self.session.policy.tool_result_max_bytes:
            result = error('tool_result_too_large')
        async with asyncio.timeout(self.session.policy.tool_timeout_seconds):
            await self.session.authorize()  # Recheck revocation after lookup/cache access.
            if call.id in self.session.cancelled:
                return
            self.session.cache[call.id] = result
            if not result.get('ok'):
                self.session.measurements.tool_error_count += 1
            self.session.measurements.mark_input_activity()
            await self.connection.send_tool_responses([{'id': call.id, 'name': call.name, 'response': result}])
            if result.get('ok') and call.name in ('search_knowledge', 'get_knowledge_entry'):
                items = result.get('items', [result])
                self.outbox.put({'type': 'knowledge_sources', 'sources': [
                    {key: item[key] for key in ('id', 'title', 'source_url', 'version')} for item in items
                ]})

    async def run(self):
        try:
            while True:
                call = await self.queue.get()
                if call.id in self.session.cancelled:
                    self.pending.discard(call.id)
                    continue
                self.active_id = call.id
                self.active = asyncio.create_task(self.respond(call))
                try:
                    await self.active
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    self.pending.discard(call.id)
                    self.active_id = self.active = None
        finally:
            if self.active is not None:
                self.active.cancel()
                await asyncio.gather(self.active, return_exceptions=True)
            self.pending.clear()
            while not self.queue.empty():
                self.queue.get_nowait()
