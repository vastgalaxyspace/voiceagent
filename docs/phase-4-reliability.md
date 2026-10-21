# Phase 4 — Reliable conversation engine

Implemented on 17 October 2026. This phase adds bounded provider/session recovery, temporary app reattachment, database leases, and graceful shutdown to the authenticated Phase 3 backend. Phase 5 now supersedes this guide's statements about future allowance and estimated-spend enforcement; payments, memory, and deployment remain later phases.

## Architecture

The WebSocket route now authenticates an attachment rather than owning the whole conversation task:

```text
Authenticated app socket
        |
SessionChannel (replaceable socket, bounded input, no replay)
        |
SessionRegistry / ManagedSession (one runtime per conversation)
        |
Relay (concurrent audio, deadlines, checkpoint-only resumption)
        |
GeminiProvider (a fresh connection using the SAME provider resume handle)

SessionRegistry <-> PostgreSQL (short lease/auth/state/finalization transactions)
```

The registry owns runtime tasks independently of a single ASGI WebSocket request. A client disconnect therefore does not automatically cancel a resumable conversation. A `SessionChannel` can replace its socket after fresh authentication, while old readers are prevented from feeding or detaching the new attachment.

The existing local, single-worker pilot and one-live-runtime-per-process cap remain. Database constraints also allow at most one live conversation per user. This phase does not introduce a distributed socket router or increase model-spending allowances.

## Gemini connection recovery

Every provider connection enables `SessionResumptionConfig`. The relay retains the latest usable `session_resumption_update` handle in memory only. A nonresumable update clears that handle. Provider handles are never sent to clients, written to conversation snapshots, saved in reports, or logged.

On `GoAway` or an allowlisted transient transport/provider failure, the relay:

1. Stops forwarding audio and cancels the current connection's upload/download tasks.
2. Closes the old provider connection.
3. Discards queued microphone audio, response audio, and stale control events.
4. Marks the conversation reconnecting and notifies an attached client.
5. Waits for an attached app if it is disconnected.
6. Reconnects with the usable handle and the original model/instructions/configuration.
7. Marks the conversation active and sends `resumed` after setup succeeds.

There is no automatic fresh-session fallback. Missing/invalidated checkpoints, rejected handles, authentication failures, and exhausted retry budgets end explicitly. Initial setup failures are not silently retried as a new conversation. The total provider resume-attempt budget applies across the whole conversation, not separately to each failure incident.

Retryable codes are limited to transport/network failures and selected timeouts, rate limits, service errors, and WebSocket rotation/closure codes. Invalid requests or credentials do not enter a retry loop. Backoff defaults to 0.25, 0.5, then 1 second, capped at 2 seconds per delay. Setup and I/O timeouts still apply.

Resumption restores the provider's usable checkpoint, not a sample-exact replay of audio around the interruption. Audio captured while recovery is pending is discarded. A nonresumable generation state ends safely instead of restoring an older, potentially incomplete state without notice. Actual model/checkpoint behavior still requires credentialed Gemini testing.

## App disconnection and reattachment

If the app disconnects, the current provider connection closes; it is not left generating speech during the reconnect grace period. When a usable checkpoint exists, the runtime stays available for 10 seconds by default.

Reconnect to `/ws/live` and send the same authenticated start message with the same conversation UUID. The backend rechecks the token and ownership. Reattachment requires the same authentication session as the original attachment, not merely another login for the same account. A second simultaneous attachment is rejected without affecting the first.

Grace, token expiry, lease expiry, and the original conversation-duration deadline are checked independently. Reconnecting does not reset those deadlines. A disconnected conversation with no usable checkpoint ends explicitly rather than opening a new context. If grace expires, it ends as `client_reconnect_timeout` and releases the live slot.

The browser's `LiveTransport` reuses the same conversation UUID and in-memory token, uses bounded retries/deadlines, pauses microphone upload during recovery, clears scheduled playback, and cleans up reconnect/heartbeat timers on stop. It does not create a second conversation on network recovery. The browser may fetch the owner's final HTTP report if the last socket message was lost.

Closing/reloading the page loses its in-memory token and runtime UI state; this phase does not provide cross-page or cross-device session takeover. A backend process restart also loses provider checkpoints. Those cases require a new conversation after the previous record is finalized/recovered.

## Protocol v3

The authenticated start frame and PCM formats from Phase 3 remain:

```json
{"type":"start","conversation_id":"OWNED_CONVERSATION_UUID","access_token":"LOGIN_TOKEN"}
```

Native clients may instead send the bearer token in their Authorization header. Tokens and provider handles never belong in the URL. Unknown start fields are rejected.

Server controls:

| Event | Client action |
| --- | --- |
| ready | Begin PCM upload; protocol version is 3 |
| reconnecting | Pause PCM upload and clear scheduled playback |
| resumed | Resume capture upload/playback on the same conversation |
| interrupted | Stop and clear assistant playback |
| turn_complete | Current model turn ended |
| pong | Transport heartbeat response; not meaningful user activity |
| ended | Read the final metadata report and clean up |
| error | Stop retrying this rejected attachment; display its safe code |

`ready` and `resumed` include `remaining_seconds`, `reconnect_grace_seconds`, and `heartbeat_interval_seconds`, in addition to audio formats and session/model identifiers. The recommended heartbeat interval is at most five seconds and adapts to the transport timeout. `remaining_seconds` is informational; server-side deadlines remain authoritative.

Clients send `{"type":"ping"}` for transport liveness. Heartbeats and silent audio do not renew user idle time. A silent/dead transport is detached after its timeout and provider audio is stopped. The watchdog remains active while awaiting reattachment or provider setup.

`{"type":"stop"}` and `{"type":"audio_end"}` remain supported. The new authenticated `POST /api/v1/conversations/{id}/stop` reaches a local runtime even when its audio socket is detached. It can also cancel a created-but-unstarted record, is owner-scoped, and is idempotent after termination. A healthy runtime owned by another process is not force-stopped through an unsafe database overwrite.

## Conversation state and leases

States are now `created`, `connecting`, `active`, `reconnecting`, `ended`, and `failed`. The partial unique user index covers all three live states.

An atomic claim records a private runtime-owner identifier and lease expiration. Defaults are a 30-second lease and five-second heartbeat. Each successful heartbeat renews the database lease, revalidates authentication, then updates the runtime's observed monotonic deadline. These are short transactions; no database connection is pinned to a live audio stream.

A database outage cannot extend a locally observed lease. If that deadline expires, the relay stops with `lease_lost`. A resumed/transitioned/finalized runtime must still match the owner and an unexpired lease. A late old worker cannot overwrite a record already recovered by another process.

At startup and periodically, recovery selects at most 100 expired live records per pass using `FOR UPDATE SKIP LOCKED` on PostgreSQL, rechecks expiration, and marks them failed with `runtime_lost`. Healthy leases belonging to other workers are left alone. This releases stale per-user active slots after an abrupt process crash. Recovery does not fabricate transcripts, provider state, or exact usage: the minimal report marks usage incomplete and cost unknown.

Lease timing assumes a correctly configured server clock. While leases fence database updates, socket routing and provider checkpoints remain process-local. Use the supplied one-worker launcher; cross-worker reconnection routing is outside this phase.

## Finalization and shutdown

After provider cleanup, finalization conditionally stores the report under the owning lease. Transient database failures are retried up to three times with short backoff. Repeating finalization after an uncertain commit is idempotent; a recovered/fenced record is never overwritten.

If finalization cannot be confirmed, `persisted` is false and a content-free error is logged. The runtime releases its in-memory slot; the database recovery loop later clears an expired remaining live record. Optional filesystem reports remain metadata-only and are disabled by default.

Graceful shutdown rejects new attachments, stops maintenance, signals all runtimes with `server_shutdown`, closes provider connections, and attempts bounded finalization before closing the database engine. Cancellation shielding protects cleanup without making retry/setup operations unlimited.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| CLIENT_RECONNECT_GRACE_SECONDS | 10 | Maximum eligible detached-client grace, up to 30 seconds |
| CLIENT_TRANSPORT_TIMEOUT_SECONDS | 15 | No incoming audio/control frames before detaching a ready transport |
| PROVIDER_RESUME_ATTEMPTS | 3 | Total resume attempts per conversation; 0 disables retries |
| PROVIDER_RESUME_BACKOFF_SECONDS | 0.25 | Initial exponential retry delay |
| LEASE_SECONDS | 30 | Runtime ownership lease |
| LEASE_HEARTBEAT_SECONDS | 5 | Lease renewal/authentication/recovery interval |

Configuration requires the lease to cover at least three heartbeat intervals. Existing session, idle, setup, and I/O limits remain. Lease/reconnect operational settings are server policy; the existing immutable conversation snapshot still determines the selected model, prompts, product deadlines, compression, and usage mode.

## Migration and local run

Stop the older backend before applying the migration. `0002_session_recovery` adds owner/lease columns, expands the state constraint and active-user index, and adds an index for live lease expiry. Prior Phase 3 active rows are finalized as failed with `migration_interrupted`, since the stopped process's provider state cannot be recovered. Created and historical terminal records are preserved.

```powershell
.\scripts\migrate.ps1
.\scripts\run.ps1
```

No new packages are needed beyond Phase 3. Existing table-level runtime grants cover the new conversation columns; migration/schema ownership still requires the separate owner connection. Follow the [Phase 3 setup guide](phase-3-foundation.md) for credentials and role setup. Do not expose this local pilot through a public tunnel.

## Measurements

Reports add provider reconnect count, client reattachment count, total resume attempts, and discarded input packets. Token samples include a connection index so counter behavior can be compared across provider connections. Provider handles are absent from all reports.

Any provider resume attempt makes the automatic dollar estimate unavailable until resumed-counter/billing semantics are separately calibrated. `usage_counter_scope` identifies `single_connection` versus `resumption_unverified`. Existing raw token reports remain bounded to the latest 100 samples. This phase does not implement budget enforcement or assume reconnects are free.

## Verification and limits

```powershell
.\scripts\check.ps1
```

The normal suite uses temporary SQLite databases. Set `TEST_DATABASE_URL` as documented in Phase 3 to run the same migration, ownership, lease, and recovery tests against isolated PostgreSQL schemas.

Verified locally: 81 Python tests passed against PostgreSQL 18; the SQLite run passed 80 with the PostgreSQL-only permissions test skipped. All 11 JavaScript tests, JavaScript syntax checks, Python compilation, and dependency checks passed. The test client emits an upstream Starlette/httpx deprecation warning.

Tests inject checkpoint messages, `GoAway`, network failures, rejected handles, invalidated checkpoints, duplicate sockets, disconnect/rejoin, lease expiry/outage, finalization failures, and shutdown. Browser transport tests use fake sockets and timers to check bounded retries, identity reuse, discarded gap audio, heartbeat cleanup, and stop behavior. Gemini is simulated; tests do not incur provider charges.

Live Gemini resumption, microphone playback quality, and end-to-end latency remain unverified without credentials and device testing. No new allowance/billing, memory, tool, or deployment features are included.

Sources checked for the provider contract:

- [Gemini Live session management](https://ai.google.dev/gemini-api/docs/live-api/session-management)
- [Google GenAI Python SDK](https://github.com/googleapis/python-genai)
