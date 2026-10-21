# Phase 5 — Cost and usage enforcement

Implemented on 18 October 2026. This phase adds backend-enforced connected-time allowances, optional estimated-spend guards, atomic reservations, idempotent settlement, conversation-creation rate limiting, and administrator usage visibility. It does not add payments, subscriptions, invoices, or automated reconciliation with a Google billing account.

## Enforcement model

Product allowance and provider cost remain separate:

```text
Conversation creation -> atomic hourly rate counter
WebSocket admission    -> reserve UTC-day seconds and optional USD capacity
Live relay             -> enforce reserved duration and optional measured-cost threshold
Terminal cleanup       -> settle actual duration/cost exactly once
Crash recovery         -> conservatively settle the remaining reservation
```

Connected time is the user-facing allowance. Provider-reported tokens produce an estimated model cost. Microphone bytes and wall-clock time are never presented as an invoice.

The default product allowance is 900 connected seconds per user per UTC day. Admission reserves at most the configured session maximum. If less time remains, the session receives the remainder when it is at least `MINIMUM_SESSION_SECONDS`; otherwise admission returns `daily_allowance_exhausted`. The relay's authoritative duration limit is reduced to the reserved amount, so reconnecting cannot obtain more time.

## Atomic reservation and settlement

`daily_usage` has one row per user and UTC date. Admission creates the row if needed and locks it, then computes:

```text
available seconds = daily limit - settled seconds - active reservations
available spend   = daily limit - settled estimate - active reservations
```

The reservation and the conversation's `created -> connecting` claim commit in the same short transaction. A failed claim rolls both changes back. A unique `usage_reservations.conversation_id` prevents one conversation from reserving twice.

Every terminal path settles the reservation in the same transaction as conversation finalization. Settlement moves reserved values into settled values, records completeness, and changes the reservation from `reserved` to `settled`. Repeating settlement after an uncertain commit is safe. A stale lease recovery charges the full connected-time reservation and, when enabled, the full spend reservation because exact missing usage cannot be reconstructed safely.

Final settlement also checks whether provider activity remains unreported. Microphone upload attempts and audio-end controls mark activity pending before awaiting provider I/O; assistant output also marks it pending. Only usage reported at a completed turn, or after that boundary without newer activity, can clear it. Metadata from a response does not acknowledge new input streamed while that response was being generated. Stopping mid-turn, logging out, duration expiry, provider errors, and shutdown therefore cannot release spend based only on an earlier turn's estimate. With the guard enabled, uncertain sessions consume their spend reservation; completed, fully reported turns release unused capacity. Continuous or overlapping microphone input can conservatively leave a session incomplete even when some token samples are available.

Reports expose `usage_complete` and `unreported_provider_activity`. `observed_model_cost_usd` preserves a computable estimate from received token reports; it can be a partial observation. `estimated_model_cost_usd` is withheld when newer activity remains unreported. Existing raw usage samples and token counts are retained. These completeness flags describe the backend's observations; they do not replace provider billing reconciliation.

Reservations are assigned to the UTC date on which provider admission begins. A conversation crossing midnight settles against that original date. The user endpoint returns the next UTC reset time so a Kotlin client can display it in local time.

## Estimated-spend guard

The cost guard is implemented but disabled by default. Enable it only after a credentialed benchmark establishes whether Gemini usage events are `per_response` or `cumulative` for the selected account and model:

```env
USAGE_MODE=per_response
COST_GUARD_ENABLED=true
DAILY_ESTIMATED_COST_LIMIT_USD=0.60
SESSION_ESTIMATED_COST_LIMIT_USD=0.20
COST_GUARD_MARGIN_RATIO=0.20
COST_USAGE_TIMEOUT_SECONDS=30
```

Configuration fails at startup if the guard is enabled with `USAGE_MODE=unknown` or a model absent from the backend price table. Existing conversations whose immutable snapshots lack verified cost tracking are denied before reservation.

The relay computes cost only from provider-reported token categories and the selected model's price table. With the default 20% safety margin, a USD 0.20 reservation triggers a stop when a reported estimate reaches USD 0.16, leaving room for delayed metadata and audio already in flight. This is a best-effort guard; delayed usage events can overshoot the threshold and it cannot guarantee an invoice cap. Actual measured settlement is not capped to the reservation, so an overrun remains visible instead of being hidden.

Incomplete usage under an enabled guard ends with `cost_tracking_unavailable`. Missing or stale provider usage also ends the session after `COST_USAGE_TIMEOUT_SECONDS` (30 seconds by default, measured from readiness or the last usage report). This can end a long turn before its final usage event arrives; calibrate the timeout for the product. Provider resumption also ends with that reason while cross-connection counter semantics remain uncalibrated. With the guard disabled, Phase 4 resumption behavior is unchanged and incomplete-cost sessions remain visible in accounting.

Prices are exact decimals in PostgreSQL, not floating-point values. The Developer API rates in `app/core/pricing.py` were rechecked on 18 October 2026. Gemini Live uses compounding context billing, so a fixed duration does not imply a fixed token cost.

## Rate limiting

Conversation record creation uses a database-backed fixed UTC-hour window. The default is ten creations per user per hour. The insert/increment is atomic, so parallel requests cannot bypass it. Exceeding it returns HTTP 429 with `conversation_rate_limited`.

This limit protects database and prompt-snapshot creation. Live admission is separately protected by the daily allowance, spend reservation, and one-live-conversation constraint. Authentication endpoint rate limiting and network-edge controls belong in the production deployment phase.

## API

`GET /api/v1/usage/me` returns the authenticated user's current UTC-day values:

- settled, reserved, and available connected seconds;
- settled and reserved estimated cost;
- whether the cost guard is enabled;
- started, settled, and incomplete-cost session counts;
- the UTC reset timestamp.

`GET /api/v1/admin/usage?day=YYYY-MM-DD&limit=50&offset=0` returns bounded daily rows ordered by estimated cost. It requires the database `users.is_admin` flag. Ordinary users receive `admin_required`; no API can grant itself the flag.

Grant or revoke the role through the owner/operator connection:

```powershell
.\venv\Scripts\python.exe -m scripts.manage_admin --email owner@example.com grant
.\venv\Scripts\python.exe -m scripts.manage_admin --email owner@example.com revoke
```

## Schema and migration

Migration `0003_usage_enforcement` adds:

- `users.is_admin`;
- `daily_usage`, keyed by user and UTC date;
- `usage_reservations`, keyed by conversation;
- `conversation_rate_windows`, keyed by user and UTC hour;
- an admin-query index on usage date and cost;
- a user/date/status index for reservation inspection.

Foreign-key columns used for ownership and cleanup have supporting indexes. Nonnegative amounts, valid reservation states, and complete settlement shapes are database constraints. Admission claims the conversation before locking its daily accounting row, matching finalization and recovery. Settlement then locks the daily row before refreshing and locking the reservation. This ordering avoids lock cycles between admission and cleanup. No provider call occurs while these locks are held.

Stop the backend, migrate with the owner connection, reapply runtime grants, then restart:

```powershell
.\scripts\migrate.ps1
# Run scripts/database_grants.sql as the database owner.
.\scripts\run.ps1
```

The runtime role can read and update accounting rows but cannot modify `users.is_admin`, prompt versions, or migration history.

## Failure rules

- Database unavailable during admission: no provider connection opens.
- Allowance or spend exhausted: reservation and conversation claim do not occur.
- Provider setup failure after admission: the short connected duration settles normally.
- Finalization outage: reservation remains held; lease recovery later settles conservatively.
- Process crash: expired-lease recovery finalizes both the conversation and reservation.
- Unknown cost with guard disabled: duration settles and the incomplete-cost counter increases.
- Unknown cost with guard enabled: the live session fails closed.

During shutdown, maintenance is signalled to exit and the current bounded database operation is drained before the engine closes. SQLite connection creation is shielded from request cancellation; if its task is cancelled, the worker's opening result is awaited and closed before cancellation propagates. This prevents losing an SQLite connection while its background thread is opening the database. SQLite remains a test-only dependency and is loaded lazily; the PostgreSQL runtime requires no new dependency.

## Verification and limitations

Run all offline checks with:

```powershell
.\scripts\check.ps1
```

Tests cover allowance reservation, partial remaining-time denial, exact-once settlement, provider-cost stopping, hourly creation limits, admin authorization, migration/model parity, stale recovery, and all Phase 1–4 behavior. Additional regressions exercise unfinished-turn settlement across socket stop, HTTP stop, logout, shutdown, provider failure, and duration expiry; successful refunds after completed usage; overlapping input; cancelled SQLite connection creation; and maintenance draining. Gemini remains simulated in automated tests.

Follow-up verification: the complete PostgreSQL 18 suite passed 105 Python tests. The current SQLite suite passed 102 with three PostgreSQL-only skips; the preceding full SQLite run also passed without the previously observed cleanup failure. All 11 JavaScript tests, syntax checks, dependency checks, and Python compilation passed. The Starlette/httpx test client still emits its upstream deprecation warning. Provider interactions remain simulated.

The USD values are operational estimates, not bills or customer balances. There is no payment ledger, refund system, subscription plan, tax handling, monthly cap, or Google Cloud Billing reconciliation. Production authentication rate limiting, alerts, retention jobs, and multi-instance coordination remain deployment work. Before enabling the cost guard, compare reports with real Gemini billing and choose limits from measured workloads.

Official references:

- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Live API billing behavior](https://ai.google.dev/gemini-api/docs/live-api/best-practices)
