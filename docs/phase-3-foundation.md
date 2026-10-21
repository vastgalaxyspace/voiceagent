# Phase 3 — Authenticated backend foundation

Phase 3 baseline. Authentication and account APIs remain current; [Phase 4](phase-4-reliability.md) supersedes the runtime lifecycle, conversation states, database revision, and WebSocket recovery behavior. It adds short periodic lease/authentication checks during streaming, while keeping database connections unpinned.

[Phase 6](phase-6-personalization-memory.md) extends preference fields and adds opt-in memory APIs. Use the latest migration head and runtime grants when following this setup guide.

Implemented on 17 October 2026. This phase adds persistent identities, revocable authentication sessions, preferences, prompt versions, and owned conversation records to the Phase 2 relay.

## Scope and implementation decisions

- FastAPI remains a modular application with separate routes, schemas, services, repositories, database models, and provider adapters.
- PostgreSQL is the application database; SQLAlchemy's asyncpg driver uses a bounded connection pool. SQLite is supported as a lightweight test backend, not the recommended application database.
- Registration and login use JSON email/password credentials. This is application session authentication, not a third-party OAuth or JWT implementation.
- Argon2id hashes passwords with 19 MiB memory, two iterations, and one lane. Verification is offloaded to a bounded thread pool. Unknown-account login performs dummy verification to reduce timing differences. Passwords have a 12–128-character bound.
- Bearer tokens contain 32 random bytes encoded in URL-safe form. Only their SHA-256 digest is stored, together with an expiration and optional revocation timestamp. Tokens default to 24 hours, and logout revokes the current session. Re-login issues a new session; refresh tokens are outside this phase.
- The browser holds its token only in memory and clears its password field after submission. Kotlin can send an Authorization header; browser WebSockets authenticate in their first frame. Tokens never appear in WebSocket URLs.
- All conversation queries filter by the authenticated owner. Missing and foreign conversation IDs return the same 404. Requests cannot select another user's identity, a model, or system instructions.
- A conversation snapshots validated preferences and backend configuration at creation and references an immutable prompt version. A fingerprint detects changes to the stored instructions/configuration before admission.
- An atomic database update claims a conversation exactly once. A partial unique index prevents two active conversations for the same user. The existing one-live-session-per-process pilot cap is retained.
- No database connection remains checked out during voice streaming. Database operations happen at authentication/admission and finalization. Provider costs and timings remain measured by Phase 2 code.

The PostgreSQL best-practices guidance informed the foreign-key indexes, owner/time listing index, partial uniqueness constraint, bounded connection pool, and separation of owner/runtime database privileges. Ownership is enforced in private backend queries; the database must not be exposed directly to mobile/browser clients.

## Local setup

Install dependencies and create your local configuration if it does not exist:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`. Set `DATABASE_URL` to your own PostgreSQL asyncpg connection URI and `GEMINI_API_KEY` to the provider key. Example URI shape:

```text
postgresql+asyncpg://voiceagent_app:URL_ENCODED_PASSWORD@127.0.0.1:5432/voiceagent
```

Percent-encode reserved characters in credentials. No real password is included in the repository. `MIGRATION_DATABASE_URL` can supply a separate owner connection for Alembic and trusted prompt publication. It defaults to `DATABASE_URL` if not configured.

For a dedicated local database, a PostgreSQL administrator can create an owner role, runtime role, and database using PostgreSQL's `createuser --pwprompt` and `createdb` utilities. For example, run in a terminal with the PostgreSQL binaries on PATH and appropriate administrator authentication:

```powershell
createuser --pwprompt --no-superuser --no-createdb --no-createrole voiceagent_owner
createuser --pwprompt --no-superuser --no-createdb --no-createrole voiceagent_app
createdb --owner voiceagent_owner voiceagent
```

Use the owner URI for `MIGRATION_DATABASE_URL`, and the app URI for `DATABASE_URL`. Apply migrations, then run `scripts/database_grants.sql` as the owner in this dedicated database. That script grants runtime SELECT/INSERT/UPDATE on account/session/conversation tables, and SELECT-only access to prompt versions and migration history. Runtime should not use a superuser or the database-owner role.

```powershell
.\scripts\migrate.ps1
# As owner, using your local psql authentication configuration:
psql --username voiceagent_owner --dbname voiceagent --file scripts/database_grants.sql
.\scripts\run.ps1
```

The server does not create tables or run migrations automatically. `GET /health` is liveness/configuration; `GET /health/ready` checks migration readiness. Authenticated endpoints fail closed when the database is not configured or available.

Open http://127.0.0.1:8000, create an account or sign in, choose preferences, and start a conversation. API documentation is at http://127.0.0.1:8000/docs. Keep the backend local and use one worker as in the supplied launcher.

## Settings added in this phase

| Setting | Default | Meaning |
| --- | --- | --- |
| DATABASE_URL | empty | Private runtime PostgreSQL connection URI |
| MIGRATION_DATABASE_URL | empty | Optional separate owner connection |
| DATABASE_POOL_SIZE | 5 | Persistent application pool size |
| DATABASE_MAX_OVERFLOW | 5 | Extra temporary pool connections |
| AUTH_SESSION_HOURS | 24 | Bearer session lifetime, configurable 1–168 hours |
| ACTIVE_PROMPT_VERSION | phase2-v1 | Version selected for new conversations |

Existing Gemini, timeout, report, and usage settings continue to apply. Configuration is read from the repository's `.env`, independently of the terminal's working directory. Private URI values use secret configuration fields and SQLAlchemy parameter hiding.

## HTTP API

| Method and path | Authentication | Behavior |
| --- | --- | --- |
| POST /api/v1/auth/register | None | Create account and default preferences |
| POST /api/v1/auth/login | None | Verify password and return an expiring bearer token |
| POST /api/v1/auth/logout | Bearer | Revoke this token; signal its active local relay to stop |
| GET /api/v1/users/me | Bearer | Current account |
| GET /api/v1/users/me/preferences | Bearer | Current user's saved preferences |
| PATCH /api/v1/users/me/preferences | Bearer | Update language, detail, and goal |
| POST /api/v1/conversations | Bearer | Create an owned conversation and immutable configuration snapshot |
| GET /api/v1/conversations | Bearer | Paginated owner-only history |
| GET /api/v1/conversations/{id} | Bearer | Owner-only conversation metadata |
| GET /api/v1/conversations/{id}/report | Bearer | Owner-only final metadata report; 409 until available |
| GET /health/ready | None | Database/migration readiness |

Register/login bodies contain `email` and `password`. Email matching is case-insensitive by normalization. Login returns `access_token`, `token_type: bearer`, and UTC `expires_at`. Send the token as `Authorization: Bearer <token>` on authenticated HTTP requests.

Preferences accept `language` (`English`, `Hindi`, or `English and Hindi`), `response_detail` (`brief` or `detailed`), and `goal` (up to 500 characters). Omitted/null patch values leave fields unchanged. An empty goal clears it. The goal is persisted personal data; it does not grant model tool permissions or override system instructions.

Create a conversation with `{}` to use the saved goal, or `{"goal":"this session's goal"}` to override only that conversation. The profile stays unchanged. The response contains the UUID, `created` status, prompt version, preference/configuration snapshots, fingerprint, and timestamps. System prompt text is not exposed in this response.

History accepts `limit` (1–100, default 20) and `offset` (0–10,000). Results sort by newest timestamp and UUID and include `next_offset` when another page exists. Offset pagination is sufficient for the pilot; it is not a snapshot-consistent export during concurrent inserts.

HTTP errors use stable `error` codes. Validation responses omit raw input so passwords and tokens are not echoed. Authentication failures include `WWW-Authenticate: Bearer`; database exception contents are not sent to clients.

## WebSocket protocol v2

Phase 2's unauthenticated start message is replaced by a conversation-bound start. The audio encoding and subsequent stop/audio-end controls remain unchanged.

1. Register/login through HTTP.
2. Save preferences and create a conversation through HTTP.
3. Open `/ws/live`.
4. Send the start message within five seconds.
5. Wait for `ready`, then send PCM audio.

Native client with an HTTP Authorization header:

```json
{"type":"start","conversation_id":"UUID_FROM_CREATE_RESPONSE"}
```

Browser client, which cannot set that WebSocket header:

```json
{"type":"start","conversation_id":"UUID_FROM_CREATE_RESPONSE","access_token":"LOGIN_TOKEN"}
```

Authentication is checked before ownership and provider admission. An Authorization header, when present, takes precedence. Do not send conflicting credentials. A rejected start never opens Gemini. No unauthenticated compatibility route exists.

`ready` reports `protocol_version: 2` and uses the durable conversation UUID as its session ID. User preferences in the socket frame are forbidden; the backend uses the saved conversation snapshot. Profile changes take effect on newly created conversations.

The relay watches token expiration in memory and stops at expiry. Logout signals relays attached to that token in the current process. This remains a single-worker pilot; distributed revocation and recovery of active records after a process crash are Phase 4 work.

## Persistence and transactions

Tables:

- `users`: unique normalized email, Argon2id hash, active status, UTC creation time.
- `user_preferences`: one row per user; validated language/detail and goal.
- `auth_sessions`: token digest, user, expiry, optional revocation time.
- `prompt_versions`: immutable version key, instructions, content hash, creation time.
- `conversations`: owner, prompt version, snapshots, fingerprint, state, times, end reason, optional report.

Alembic revision `0001_foundation` creates the schema, constraints, indexes, and frozen `phase2-v1` prompt seed. The revision embeds its original prompt text so future code edits do not alter historical migrations.

Conversation states are `created`, `active`, `ended`, and `failed`. In this phase, `active` covers provider setup as well as streaming. An atomic conditional claim prevents duplicate starts; the database index enforces one active record per user even if two claims race. The existing process-level cap is additional, not distributed capacity management.

Finalization stores metadata after provider cleanup and runs during disconnect cancellation as well. A report includes `persisted: true` after a successful finalization. If finalization fails, the client report is marked `persisted: false` and a content-free error is logged; an active record can remain. Automatic repair after database/process failure is deliberately deferred to Phase 4.

No audio or transcripts are stored. Preference goals and account emails are now persisted intentionally. Automated retention, account deletion, email verification, password recovery, internet-facing abuse controls, daily usage allowances, billing, memory, and deployment are not implemented in this phase. The local-address/Host/Origin checks remain in place.

## Prompt version management

Use a trusted operator terminal, with an owner/publisher database connection, to insert a new immutable version:

```powershell
.\venv\Scripts\python.exe -m scripts.manage_prompts --version voice-v2 --file C:\path\to\instructions.txt
```

Existing version keys cannot be overwritten. Set `ACTIVE_PROMPT_VERSION=voice-v2` and restart to select it for future conversations. Old conversations retain their original version reference and fingerprint. Runtime database permissions prevent the application role from editing prompt versions. The initial `app/prompts/system.py` also remains the fallback used by standalone prompt unit tests; production conversation instructions come from the versioned database row.

## Verification

```powershell
.\scripts\check.ps1
```

Default API tests apply the real Alembic migration to temporary SQLite databases and use real registration/token validation with a simulated Gemini provider. PostgreSQL verification uses isolated temporary schemas:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://TEST_OWNER:URL_ENCODED_PASSWORD@127.0.0.1:5432/DEDICATED_TEST_DATABASE'
.\scripts\check.ps1
Remove-Item Env:TEST_DATABASE_URL
```

The test owner needs CREATE/DROP privileges for its randomly named `test_<uuid>` schemas. Tests create and drop only those schemas, including a migration downgrade/upgrade roundtrip. Use a dedicated test database. Never point tests at production. Provider credentials are not needed and tests make no Gemini API calls.

Coverage includes password/token storage, generic login failures, validation redaction, expiry/revocation, owner isolation over HTTP and WebSockets, immutable snapshots, prompt publication, atomic claims, persisted setup failures and disconnects, application recreation, and migration/model consistency. Browser microphone playback and live Gemini costs still require the credentialed Phase 2 benchmark.

Recorded verification on Windows / Python 3.11.4 / PostgreSQL 18: 56 Python tests passed, 5 JavaScript audio/auth tests passed, JavaScript syntax and dependency checks passed, and Alembic reported no model/schema drift. The PostgreSQL-specific test also verified that a restricted runtime role can use the API and cannot update prompt versions. The default SQLite run skips that PostgreSQL-role test. The test client emits one upstream Starlette/httpx deprecation warning.

The isolated verification database was created solely for testing; these checks did not configure or modify your application database or connect to Gemini.

## References

- [SQLAlchemy asynchronous sessions and concurrent tasks](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Alembic asynchronous migration cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic)
- [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [FastAPI authentication background](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
