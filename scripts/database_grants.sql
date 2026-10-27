-- Run as the database owner after migrations. Create voiceagent_app separately
-- with a password via createuser --pwprompt; never put that password here.
-- These grants assume the dedicated database and its public schema.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO voiceagent_app;
-- Remove the table-wide UPDATE permission granted by the Phase 3 script.
REVOKE UPDATE ON users FROM voiceagent_app;
GRANT SELECT, INSERT ON users TO voiceagent_app;
GRANT SELECT, INSERT, UPDATE ON user_preferences, auth_sessions, conversations,
    daily_usage, usage_reservations, conversation_rate_windows TO voiceagent_app;
GRANT SELECT ON prompt_versions, alembic_version TO voiceagent_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_memories TO voiceagent_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_entries TO voiceagent_app;
GRANT SELECT, UPDATE ON knowledge_state TO voiceagent_app;
-- Voice transcript history and owner-checked conversation deletion.
GRANT SELECT, INSERT, UPDATE, DELETE ON conversation_messages TO voiceagent_app;
GRANT DELETE ON conversations TO voiceagent_app;
-- Runtime cannot rewrite system prompt versions or migration history.
