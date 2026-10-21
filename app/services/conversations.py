import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.core.pricing import RATES
from app.db.models import Conversation
from app.repositories import conversations, memories as memory_repository, prompts, usage_limits
from app.services import memories, knowledge


def fingerprint(instructions: str, version: str, preferences: dict, configuration: dict) -> str:
    serialized = json.dumps({
        'instructions': instructions, 'version': version,
        'preferences': preferences, 'configuration': configuration,
    }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()


async def create(database, settings, user_id: UUID, goal: str | None, *, use_tools: bool = False):
    if use_tools and not settings.live_tools_enabled:
        raise AppError('tools_disabled', 409)
    async with database.sessions.begin() as session:
        await usage_limits.consume_creation(session, user_id, settings.conversation_creations_per_hour)
        prompt = await prompts.get(session, settings.active_prompt_version)
        if prompt is None:
            raise AppError('prompt_version_not_configured', 503)
        profile = await memory_repository.locked_profile(session, user_id)
        snapshot = {'language': profile.language, 'response_detail': profile.response_detail,
                    'goal': profile.goal if goal is None else goal,
                    'personalization_version': 1,
                    'display_name': profile.display_name, 'custom_instructions': profile.custom_instructions,
                    'conversation_mode': profile.conversation_mode,
                    'memory_context': await memories.snapshot(session, profile, settings)}
        if use_tools:
            snapshot['knowledge_context'] = await knowledge.context(session, user_id)
        configuration = {key: getattr(settings, key) for key in (
            'gemini_model', 'gemini_api_version', 'session_max_seconds',
            'session_idle_seconds', 'context_compression', 'usage_mode',
        )}
        configuration.update(live_tools_enabled=use_tools, tool_policy_version=settings.tool_policy_version)
        conversation = Conversation(
            user_id=user_id, prompt_version=prompt.version, preferences_snapshot=snapshot,
            configuration_snapshot=configuration,
            configuration_fingerprint=fingerprint(prompt.instructions, prompt.version, snapshot, configuration),
        )
        session.add(conversation)
        await session.flush()
        return conversation


async def get_owned(database, user_id: UUID, conversation_id: UUID):
    async with database.sessions() as session:
        result = await conversations.owned(session, user_id, conversation_id)
    if result is None:
        # Foreign and nonexistent IDs intentionally have the same response.
        raise AppError('conversation_not_found', 404)
    return result


async def claim(database, user_id: UUID, conversation_id: UUID, *, runtime_owner: str | None = None,
                lease_seconds: float = 30, settings=None, include_allocation: bool = False,
                include_memories: bool = False):
    try:
        async with database.sessions.begin() as session:
            existing = await conversations.owned(session, user_id, conversation_id)
            if existing is None:
                raise AppError('conversation_not_found', 404)
            if existing.status != 'created':
                raise AppError('conversation_already_started', 409)
            prompt = await prompts.get(session, existing.prompt_version)
            expected = fingerprint(prompt.instructions, prompt.version,
                                   existing.preferences_snapshot, existing.configuration_snapshot)
            if expected != existing.configuration_fingerprint:
                raise AppError('conversation_configuration_changed', 409)
            if settings and settings.cost_guard_enabled and (
                    existing.configuration_snapshot.get('usage_mode') == 'unknown'
                    or existing.configuration_snapshot.get('gemini_model') not in RATES):
                raise AppError('conversation_cost_tracking_unavailable', 409)
            conversation = await conversations.claim(session, user_id, conversation_id,
                                                     runtime_owner or str(uuid4()), lease_seconds)
            if conversation is None:
                raise AppError('conversation_already_started', 409)
            context = await memories.resolve(session, user_id,
                                             existing.preferences_snapshot.get('memory_context'), settings)
            if existing.configuration_snapshot.get('live_tools_enabled'):
                if (settings is None or not settings.live_tools_enabled
                        or existing.configuration_snapshot.get('tool_policy_version') != settings.tool_policy_version):
                    raise AppError('tools_disabled', 409)
                if not await knowledge.valid(session, user_id, existing.preferences_snapshot.get('knowledge_context')):
                    raise AppError('conversation_knowledge_changed', 409)
            allocation = await usage_limits.reserve(session, user_id, conversation_id, settings) if settings else None
            result = (conversation, prompt.instructions, allocation)
            if include_memories:
                return (*result, context)
            return result if include_allocation else result[:2]
    except IntegrityError:
        raise AppError('user_session_busy', 409) from None
