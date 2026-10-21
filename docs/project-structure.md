# Backend folder structure

The repository root is the backend project. The Kotlin app is not implemented here. Phase 8 adds a single-instance production deployment and operations controls. Application code lives in `app/`; deployment artifacts live in `deploy/`. The temporary browser test harness lives in `tools/voice_client/` and is disabled in production.

```text
voiceagent/
|-- app/
|   |-- main.py                       # Application factory and ASGI entry point
|   |-- api/
|   |   |-- dependencies.py           # Current-user authentication and database access
|   |   |-- router.py                 # Registers route modules
|   |   `-- routes/
|   |       |-- auth.py               # Register, login, logout
|   |       |-- users.py              # Current account and preferences
|   |       |-- memories.py           # Owned, opt-in memory CRUD
|   |       |-- knowledge.py          # Private CRUD/search and admin shared references
|   |       |-- conversations.py      # Owned conversation creation/history/reports
|   |       |-- usage.py              # Current user's allowance and spend estimate
|   |       |-- admin.py              # Administrator usage visibility
|   |       |-- health.py             # GET /health
|   |       |-- live.py               # WS /ws/live: admission and lifecycle
|   |       `-- harness.py            # GET /: local browser harness
|   |-- core/
|   |   |-- errors.py                 # Safe public application errors
|   |   |-- passwords.py              # Argon2id and token digests
|   |   |-- config.py                 # Validated environment configuration
|   |   |-- paths.py                  # Repository-relative filesystem paths
|   |   |-- pricing.py                # Explicit model pricing table
|   |   `-- security.py               # Local address, Host, and Origin checks
|   |-- db/
|   |   |-- base.py                   # Declarative metadata and UTC timestamps
|   |   |-- models.py                 # Users, tokens, preferences, prompts, conversations
|   |   `-- session.py                # Async engine, pool and transaction factories
|   |-- integrations/
|   |   `-- gemini/
|   |       |-- live.py               # Google SDK connection and audio adapter
|   |       |-- tool_schema.py        # Explicit read-only function declarations
|   |       `-- retry.py              # Allowlisted transient provider failures
|   |-- prompts/
|   |   `-- system.py                 # Versioned backend-owned instructions
|   |-- schemas/
|   |   |-- auth.py                   # Credentials and public account/token responses
|   |   |-- preferences.py            # Validated preference patches
|   |   |-- memory.py                 # Memory validation and versioned writes
|   |   |-- knowledge.py              # Knowledge validation and strict tool arguments
|   |   |-- conversations.py          # Conversation request/response shapes
|   |   |-- usage.py                  # User/admin usage response shapes
|   |   `-- live.py                   # Validated authenticated WebSocket start
|   |-- repositories/
|   |   |-- users.py                  # User and preference queries
|   |   |-- auth_sessions.py          # Token lookup and revocation
|   |   |-- prompts.py                # Versioned instruction lookup
|   |   |-- memories.py               # Owned memory queries and profile locks
|   |   |-- knowledge.py              # Visibility filters, lexical search and shared revision
|   |   |-- conversations.py          # Owner-scoped queries and atomic claims
|   |   `-- usage_limits.py           # Reservation, settlement and rate windows
|   |-- services/
|   |   |-- auth.py                   # Password login and bearer-session lifecycle
|   |   |-- conversations.py          # Snapshotting, ownership and admission rules
|   |   |-- memories.py               # Consent, quota, selection and context manifests
|   |   |-- knowledge.py              # Knowledge quotas, versions, revision invalidation
|   |   |-- live_tools.py             # Bounded worker, authorization, cancellation, RAM cache
|   |   |-- operations.py             # Bounded aggregate operational counters
|   |   |-- prompts.py                # Immutable operator-controlled publication
|   |   |-- live_session.py           # Concurrent relay, queues and deadlines
|   |   |-- session_channel.py        # Replaceable authenticated socket, bounded input
|   |   |-- session_registry.py       # Runtime ownership, leases and finalization
|   |   |-- prompt_builder.py         # Compose instructions and user preferences
|   |   `-- usage.py                  # Measurements and cautious cost estimation
|   `-- storage/
|       `-- reports.py                # Optional metadata report persistence
|-- migrations/
|   |-- env.py                       # Alembic async runner
|   |-- script.py.mako               # Future revision template
|   `-- versions/
|       |-- 0001_foundation.py        # Schema and immutable initial prompt seed
|       |-- 0002_session_recovery.py  # Live states, ownership leases and recovery index
|       |-- 0003_usage_enforcement.py # Allowance, reservation and rate-limit schema
|       |-- 0004_personalization_memory.py # Profiles, revisions and memory rows
|       `-- 0005_knowledge_tools.py    # Knowledge rows, revisions and PostgreSQL GIN index
|-- tools/
|   `-- voice_client/
|       |-- index.html
|       |-- auth.js                   # In-memory token and sign-in interface
|       |-- live-transport.js         # Bounded reattachment and transport heartbeats
|       |-- client.js
|       |-- capture-worklet.js
|       `-- style.css
|-- tests/
|   |-- helpers/                     # Fake provider, real migrations/auth test client
|   |-- integration/                 # Ownership, persistence, authentication and relay
|   |-- unit/                        # Configuration, SDK adapter, prompts, usage
|   `-- javascript/                  # PCM capture, authentication and recovery tests
|-- scripts/
|   |-- run.ps1                      # Start the backend locally
|   |-- check.ps1                    # Run all offline checks
|   |-- migrate.ps1                  # Apply explicit database migrations
|   |-- manage_prompts.py            # Publish a new immutable prompt version
|   |-- manage_admin.py              # Grant/revoke usage administrator access
|   |-- manage_users.py              # Operator provisioning with interactive password
|   |-- database_backup.py           # Private archives and guarded empty-target restore
|   |-- healthcheck.py               # Credential-free loopback container readiness
|   |-- database_grants.sql          # Limit the runtime database role's permissions
|   `-- summarize_benchmarks.py      # Compare metadata reports
|-- docs/
|   |-- phase-1-specification.md
|   |-- phase-2-prototype.md
|   |-- phase-3-foundation.md
|   |-- phase-4-reliability.md
|   |-- phase-5-cost-enforcement.md
|   |-- phase-6-personalization-memory.md
|   |-- phase-7-tools-knowledge.md
|   |-- phase-8-production-deployment.md
|   `-- project-structure.md
|-- deploy/
|   |-- compose.yaml                 # Private API, public TLS proxy, explicit operator job
|   |-- Caddyfile                    # HTTPS/WSS proxy and transport bounds
|   |-- requirements.txt             # Runtime-only packages constrained by root lock
|   `-- .env.example                 # Nonsecret Compose interpolation template
|-- Dockerfile                       # Non-root backend image
|-- .dockerignore                    # Build-context allowlist excluding secrets/test data
|-- .env.example                     # Configuration template; no credentials
|-- alembic.ini                      # Migration location/configuration
|-- .gitignore
|-- pytest.ini
|-- requirements.txt                 # Direct runtime dependencies
|-- requirements-dev.txt             # Runtime plus test dependencies
|-- requirements-lock.txt            # Tested full dependency snapshot
`-- README.md
```

Python package folders also contain `__init__.py`. Runtime reports, the local `.env`, `venv/`, and caches are ignored by source control. The old root-level `static/` is no longer used; the browser assets are still served at `/static/*` for protocol compatibility.

## Request flow

`app/main.py` builds the application, attaches settings and dependencies, installs local-access middleware, mounts the test assets, and registers the API router. It contains no conversation business logic.

`api/routes/live.py` validates the start message and bearer token, checks ownership, and attaches the socket through the session registry. The registry owns the conversation task independently of the request, atomically claims the stored conversation, renews its lease, persists the final report, and releases the single-process pilot slot.

`services/live_session.py` concurrently reads client audio, uploads it to the provider, receives provider output, sends client events, and watches deadlines. It resumes only with a usable provider checkpoint and a bounded retry budget. `services/session_channel.py` replaces disconnected sockets without replaying gap audio. Provider-specific connection setup and SDK calls live in `integrations/gemini/live.py`.

`services/prompt_builder.py` combines the selected immutable database prompt with the conversation's validated preference snapshot. `prompts/system.py` remains the standalone default; migrations freeze the initial version, and the operator tool publishes future versions. Instructions remain backend-owned.

HTTP routes use authenticated dependencies and focused services. Repository functions own database queries; database models define constraints and indexes. Each operation uses a short async transaction. A live audio relay does not pin a database connection for the duration of the conversation.

`services/usage.py` owns token accounting and measurement rules. `core/pricing.py` owns the supported price table. `storage/reports.py` writes metadata without knowing about WebSockets or the SDK.

`repositories/usage_limits.py` serializes daily admission with short row-locked transactions, creates one reservation per conversation, and settles it exactly once. Stale lease recovery settles abandoned reservations conservatively.

`services/memories.py` owns consent, version checks, quotas, prompt selection, and ID/hash manifests. `repositories/memories.py` owns bounded owner-scoped queries and preference-row locking. The registry stops memory-enabled runtimes after revision changes; fact text is resolved only for the provider prompt and is not copied into conversation records or reports.

## Where to make changes

| Change | Location |
| --- | --- |
| API route or endpoint behavior | `app/api/routes/` |
| New validated request shape | `app/schemas/` |
| Session orchestration or interruption handling | `app/services/live_session.py` |
| Client attachment and bounded socket input | `app/services/session_channel.py` |
| Runtime leases, stale recovery and finalization | `app/services/session_registry.py` |
| Gemini API integration | `app/integrations/gemini/live.py` |
| New system prompt version | `scripts/manage_prompts.py` and `app/services/prompts.py` |
| Account and token lifecycle | `app/services/auth.py` and `app/core/passwords.py` |
| Database schema | `app/db/models.py` and an Alembic revision in `migrations/versions/` |
| Ownership queries | `app/repositories/conversations.py` |
| User preference composition | `app/services/prompt_builder.py` |
| Environment setting | `app/core/config.py` and `.env.example` |
| Supported model prices | `app/core/pricing.py` |
| Measurement/accounting rules | `app/services/usage.py` |
| Allowance reservation and settlement | `app/repositories/usage_limits.py` |
| Memory consent, selection and version checks | `app/services/memories.py` |
| User-memory API | `app/api/routes/memories.py` |
| Optional benchmark file storage | `app/storage/reports.py` |
| Temporary microphone/player harness | `tools/voice_client/` |

`services/live_tools.py` executes only the three declared read tools. A separate bounded worker leaves relay upload/download free while tools use short database operations. The authenticated identity, active lease, and knowledge revisions are checked before lookup and before sending results. Tool payloads remain in RAM; reports contain counters only. PostgreSQL retrieval uses the same expression as the GIN index; SQLite uses escaped substring matching for tests.

`core/security.py` keeps local access isolation and adds production HTTPS/origin checks, bounded JSON buffering and process-local authentication admission. `services/operations.py` retains aggregate counters without request content. Administrator operations endpoints expose those counters and drain admission. Production uses exactly one worker and one active voice session; startup requires the current migration and verified PostgreSQL TLS.

Phase 7 includes manual plain-text knowledge and lexical retrieval. Payments, invoices, subscriptions, automated provider-billing reconciliation, transcript extraction, remote document ingestion, and semantic retrieval are not included.

## Compatibility and verification

The ASGI command stays `app.main:app`. Existing endpoint paths remain. WebSocket protocol v3 requires a bearer token and a previously created owned conversation, and adds recovery events and heartbeat guidance. There is no unauthenticated Phase 2 compatibility endpoint. Relative report paths resolve from the repository root, and `.env` is also loaded from that root.

Use `scripts/check.ps1` from the repository root, or invoke it by absolute path from another directory. It runs unit/integration tests with real migrations/authentication, browser audio tests, JavaScript syntax checks, and dependency checks. API tests default to temporary SQLite databases; `TEST_DATABASE_URL` enables isolated PostgreSQL schemas. Tests simulate Gemini, so live provider validation still needs a credentialed run. See the Phase 3 guide for database setup and privileges.
