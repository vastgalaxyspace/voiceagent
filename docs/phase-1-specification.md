# Phase 1 — Product and cost specification

Date: 16 October 2026

Status: planning baseline complete; assumptions remain provisional; feasibility is unmeasured.

## 1. Purpose and boundary

Define what the backend must do, the initial architecture, measurable quality targets, and how costs will be evaluated before implementing a voice prototype.

The user has selected Kotlin for the app, FastAPI for the backend, Gemini Live for full duplex interaction, and cost efficiency as a priority. Backend implementation is the current focus. Application-wide system instructions and user-specific instructions must be supported.

This phase produces documentation only. It does not install dependencies, choose a hosting subscription, provision services, create credentials, or implement application endpoints.

## 2. Product definition

The provisional product is an authenticated, one-to-one voice conversation between a user and an AI assistant. The user can speak while the assistant is speaking and interrupt its response.

Live translation between two people is outside this baseline. If translation is the intended product, revisit the model evaluation and turn-handling design before Phase 2.

### Provisional starting assumptions

| Decision | Planning default | Reason / validation needed |
| --- | --- | --- |
| Initial conversation mode | General voice assistant | Domain-specific behavior has not been specified |
| Initial languages | English and Hindi, including natural switching | Validate recognition, output quality, and mixed-language behavior |
| Typical session | 5 minutes | Used to define benchmark scenarios |
| Hard session limit | 10 minutes | Initial exposure bound; configurable |
| Idle timeout | 60 seconds without meaningful user activity, after pending output finishes | Heartbeats must not extend an idle conversation |
| Per-user concurrency | 1 active session | Avoid duplicate sessions and accidental parallel spending |
| Initial allowance | 15 connected minutes per user per UTC day | Provisional product allowance; actual model spend also needs a separate guard |
| Pilot load | 10 simultaneous conversations | Capacity test target, not a capacity claim |
| Initial deployment | One region, one application instance | Validate latency from intended users before selecting a region |
| Spoken response style | Usually 1–3 short sentences | More detail when requested; measure actual output duration |
| Audio recording | Disabled | Avoid storage expense and unnecessary retention |
| Transcript persistence | Disabled initially | Enable only if the feature requires it |
| Cross-session memory | Deferred to Phase 6 | Establish reliable voice behavior and cost first |

The allowance uses connected duration so it remains understandable to users. Connected time is not a substitute for provider token accounting and is not a guarantee of a fixed model cost.

## 3. Initial scope

### Required for the eventual first usable backend

- Authenticated session creation and ownership checks.
- A secure app-to-backend WebSocket carrying audio and control events.
- A server-side Gemini Live session for each admitted conversation.
- Concurrent microphone upload and model output forwarding.
- Interruption propagation and removal of stale queued response audio.
- Server-managed system instructions and validated user preferences.
- Session deadlines, idle cleanup, concurrency limits, and usage accounting.
- Provider disconnection handling and bounded resumption attempts.
- Error and latency monitoring without recording audio content.

### Deferred capabilities

- Video, telephone calls, group conversations, and human-to-human translation.
- Payments, subscription billing, and a web administration interface.
- External action tools and document retrieval.
- Persistent transcripts, recordings, vector search, and long-term memory.
- Multiple deployment regions, microservices, Kubernetes, and automatic failover.

Deferred features are not prerequisites for validating the voice architecture.

## 4. Architecture decision

### Initial data flow

Android app ⇄ secure WebSocket ⇄ FastAPI conversation service ⇄ Gemini Live

FastAPI ⇄ PostgreSQL for durable users, preferences, prompt versions, conversation records, and usage.

FastAPI → operational monitoring for connection counts, errors, latency, and estimated cost.

FastAPI → secret storage for Gemini credentials. Permanent credentials never go to the app or into a prompt.

The backend relays audio initially. This centralizes provider integration, session shutdown, prompt composition, and usage observations. It introduces bandwidth cost and another network hop.

Direct Android-to-Gemini streaming with restricted ephemeral credentials remains a later optimization candidate. It needs separate validation of session restrictions, authoritative usage accounting, and enforcement of already-issued credentials. A database flag alone must not be assumed to terminate a direct provider connection.

### Module responsibilities

| Module | Responsibility |
| --- | --- |
| Authentication | Verify identity and attach the server-derived user identity |
| Preferences | Validate supported language and response-style choices |
| Prompt composition | Resolve versioned instructions and relevant user context |
| Session manager | Admission, ownership, state, deadlines, cleanup, reconnect policy |
| Gemini adapter | Provider setup, audio forwarding, provider events and usage normalization |
| Usage and limits | Reserve allowance, record usage, estimate cost, enforce bounds |
| Persistence | Durable conversation and accounting records |
| Observability | Operational metrics, content-free logs, error classification |

Use one modular application. Redis becomes necessary when admission and session coordination span multiple processes or instances; it is not required merely to begin a single-process prototype. A later worker handles durable summary and reconciliation jobs. PostgreSQL is planned for the backend foundation, not required for the single-session feasibility experiment.

## 5. Session contract

1. Authenticate the user and validate requested settings.
2. Atomically check/reserve the active-session slot and available allowance.
3. Create an owned conversation record with its configuration and prompt version.
4. Bind an authenticated app connection to that record.
5. Open the provider connection and wait for setup confirmation.
6. Signal ready and relay audio in both directions.
7. Observe activity, interruptions, usage, deadlines, and disconnects.
8. Resume the provider session where supported, within a bounded retry policy.
9. Close both sides, finalize accounting, and release reservations on every terminal path.

Conceptual states: created → connecting → active → reconnecting → active → ending → ended. A session may enter failed from any nonterminal state. Terminal cleanup must be safe to repeat.

An app conversation identifier is distinct from a provider connection identifier. Reconnection must preserve ownership and accounting without spending the same reservation twice.

If the app disconnects, stop upstream audio and generation as promptly as possible. Permit at most a provisional 10-second reconnect grace period before closing an otherwise orphaned provider session. Never replay a long backlog of captured audio.

Provider limits, resumption rules, and mutable configuration must be checked for the selected model and API version. They are not hard-coded assumptions in this specification.

## 6. Prompt and personalization specification

Compose these conceptual layers:

1. Backend-owned application instructions: role, conversational behavior, tool boundaries.
2. Backend-owned conversation mode: the selected experience.
3. Validated user preferences and clearly labeled user-provided context.
4. Current user speech or text as ordinary conversation input.

Initial application behavior: be clear, answer briefly by default, ask one question at a time where helpful, and acknowledge uncertainty. The exact domain persona remains provisional.

Initial profile fields: preferred language, response detail preference, and optional conversation goal. User-entered free text is lower-trust context and cannot grant permissions or override application rules.

Provisional prompt budget: target at most 1,000 tokens for composed startup instructions and profile context, with user-entered goal text limited to 500 characters. Measure using the selected model's supported counting or usage facilities; characters are not equivalent to tokens. These are design budgets, not provider limits.

Record the prompt version and a configuration fingerprint for each conversation. Do not log raw personalized prompts by default. Saved preference changes apply to the next session initially.

Authorization and spending limits are enforced by backend logic, never solely by instructions to the model.

## 7. Cost model

### Separate product allowance from provider cost

Track connected duration for the user-facing allowance. Track provider-reported usage categories for model cost. Track infrastructure separately.

Model cost = sum of billable tokens per category × that category's price per million tokens ÷ 1,000,000, plus any separately billed features.

Total service cost = model cost + compute + network egress + database + storage + background processing + monitoring.

Do not derive provider charges from microphone bytes or connected minutes alone. Retained context, response length, model-specific listening behavior, transcription, and retries can change the result.

### Pricing inputs to capture during Phase 2

| Input | Requirement |
| --- | --- |
| Exact model ID and API platform | Record the model actually accessible to the account |
| Text input rate | Verify against official pricing |
| Audio input rate | Verify against official pricing |
| Text output rate | Include transcription and other billed text where applicable |
| Audio output rate | Verify against official pricing |
| Thinking / additional features | Identify how the chosen model accounts for them |
| Context billing and compression | Verify behavior for the selected configuration |
| Usage event semantics | Establish whether reports are cumulative or incremental before summing |
| Infrastructure prices | Fill in after deployment provider and region are selected |

No fixed production price or verified monthly estimate is claimed in Phase 1. Rates from an earlier discussion must be rechecked when the exact model and platform are selected.

### Provisional economic targets

- Target model cost: at most USD 0.10 for the standard 5-minute benchmark conversation.
- Review threshold: USD 0.20 for that same benchmark; investigate model choice, history size, and output duration if exceeded.
- These are planning targets, not quoted rates or enforced production balances.
- A monthly infrastructure cap remains undecided until hosting and expected traffic are specified.

Monthly forecast = users × sessions per user per month × measured average model cost per session + infrastructure. Also forecast a high-usage case using measured expensive-session samples and peak concurrency.

### Standard benchmark workload

A 5-minute conversation with approximately 10 user turns, 2 minutes of user speech, 2 minutes of assistant speech, and 1 minute of pauses. Include two interruptions and one language switch. Measure the audio actually sent, since pauses may still be streamed.

Also test a 10-minute conversation with more turns, an idle session, a disconnected client, and a reconnect scenario. Compare both total cost and cost of later turns to expose retained-context effects.

### Planned controls

- Session duration, idle timeout, daily connected allowance, and one-session admission limit.
- Short default responses and bounded context configuration where supported.
- No transcription, recording, tools, or extra model calls unless required by the experiment.
- Allowance reservations with idempotent settlement and recovery after failures.
- Estimated spend guard with a margin for delayed usage and in-flight generation; calibrate that margin from measurements.
- Reconciliation against available provider billing records; never trust client-reported usage alone.

Local VAD and context compression are optimization candidates, not assumed savings. Validate endpointing quality and billing effects before enabling them as cost controls.

## 8. Measurable acceptance targets

All targets below are provisional and have not been tested.

| Metric | Definition | Initial target |
| --- | --- | --- |
| Ready latency | Session request to confirmed provider readiness | p95 ≤ 3 seconds |
| Response latency | End of user speech to first audible assistant sample on Android | p50 ≤ 1 second; p95 ≤ 2 seconds |
| Interruption latency | User speech onset to stopped assistant playback | p95 ≤ 300 milliseconds |
| Relay overhead | Backend receive-to-forward time per audio packet | p95 ≤ 50 milliseconds |
| Session cleanup | Terminal failure or expired grace period to upstream closure and reservation release | ≤ 5 seconds |
| Pilot concurrency | Simultaneous active relay sessions under benchmark traffic | 10, with bounded queues and no orphaned connections |
| Session reliability | Benchmark sessions completing without an unhandled backend error | ≥ 95% in at least 100 controlled runs |
| Model economics | Standard 5-minute benchmark | Target ≤ USD 0.10; review above USD 0.20 |
| Isolation | Attempts to join/read another user's session | All denied |

Report test device, network, region, model, and sample size with results. Backend-only timing cannot establish end-to-end playback or interruption latency; final validation needs Android instrumentation. Until then, a test client supplies a transport-level proxy measurement clearly labeled as such.

Evaluate speech quality manually with a fixed English/Hindi scenario set: understanding, pronunciation, mixed-language behavior, appropriate brevity, and interruption recovery. Cost optimization fails acceptance if it materially damages conversation quality.

## 9. Data and operational baseline

- Raw audio and permanent transcripts are disabled by default.
- Store minimal operational metadata: owner, conversation state, model/configuration, prompt version, timestamps, usage categories, estimated cost, and error codes.
- Proposed pilot retention: 30 days for operational conversation metadata and 14 days for diagnostic logs. Financial record retention must be revisited if payments are added.
- Profiles persist until changed or deleted. Account deletion must address dependent records and any later-added memories or recordings.
- Use UTC timestamps; present dates in the user's timezone.
- Protect credentials, resumption handles, tokens, and user content from logs.
- Start with metrics for active sessions, admission denials, response timing, interruptions, disconnects, queue pressure, estimated spend, and cleanup failures.
- Alert on orphaned sessions, repeated provider setup failures, and unexpected spend growth.

## 10. Risks and open decisions

| Topic | Current decision / required validation |
| --- | --- |
| Product domain | General assistant assumed; confirm before polishing prompts |
| Languages | English/Hindi assumed; validate intended audience |
| Model | Select an account-accessible native-audio Live model through a quality/cost comparison |
| Authentication | Provider not selected; keep identity integration separate from conversation logic |
| Hosting | Provider/region not selected; benchmark from intended users |
| Budget | Per-session target proposed; total monthly cap requires owner input |
| Audio echo | Android audio configuration and device testing required |
| Cost growth | Measure retained-context costs over multi-turn sessions |
| Provider evolution | Revalidate preview status, limits, rates, and supported settings at implementation |
| Privacy | Confirm retention and whether personalization later needs durable history |

These decisions do not prevent a bounded local Phase 2 experiment. They must be settled before exposing a paid or public service.

## 11. Phase 1 completion and Phase 2 handoff

Phase 1 deliverables are complete when the repository contains the product scope, provisional assumptions, architecture decision, session lifecycle, prompt layering, cost calculation, benchmark workload, acceptance targets, and open-decision register. This document supplies those deliverables.

Phase 2 may implement only a bounded feasibility prototype: one test client, one FastAPI relay, one Gemini Live session, interruption handling, guaranteed cleanup, and usage measurements. It should compare short and long benchmark conversations and record actual quality, latency, and cost.

Phase 2 must first choose the exact model, verify official pricing and feature limits, and use locally configured credentials. Production authentication, database integration, payments, memory, and deployment remain later work.

## References to verify during implementation

- [Gemini Live overview](https://ai.google.dev/gemini-api/docs/live-api)
- [Live API capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Session management](https://ai.google.dev/gemini-api/docs/live-api/session-management)
- [Live API best practices and billing behavior](https://ai.google.dev/gemini-api/docs/live-api/best-practices)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/)
