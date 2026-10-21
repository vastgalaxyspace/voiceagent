# Phase 6 — Personalization and user-managed memory

This phase adds custom instructions, conversation modes, and explicit cross-session memory to the authenticated backend. Memory is disabled by default for each account. No audio or transcript extraction, embeddings, vector database, or additional model calls are introduced. The existing browser remains an audio test harness; these APIs are available through `/docs` and to the future Kotlin client.

## Architecture and cost

```text
Authenticated preference/memory API
        |
UserPreferences + UserMemory in PostgreSQL
        |
Conversation creation -> bounded selection -> immutable ID/version/hash manifest
        |
Live admission -> revalidate consent/revision -> resolve selected facts
        |
Backend mode + application rules + lower-trust user-context JSON
        |
Existing Gemini Live session, accounting and recovery engine
```

There is no background model or paid summarization job. Selection is deterministic: highest priority first, then creation time and UUID, with at most five memories and 1,800 UTF-8 bytes of serialized memory JSON by default. Facts that do not fit are skipped rather than truncated; later smaller facts can still fit. This is a byte budget, not a token count. Startup instructions, profile fields, and goals have their own field bounds and add to the full prompt. Actual latency, tokens, and quality still require live testing.

## Personalization

`PATCH /api/v1/users/me/preferences` accepts the existing language, response detail, and goal, plus:

| Field | Default | Bound / behavior |
| --- | --- | --- |
| display_name | empty string | At most 80 characters |
| custom_instructions | empty string | At most 1,000 characters; lower-trust requests |
| conversation_mode | general | general, english_practice, interview_practice |
| memory_enabled | false | Explicit permission to include saved facts in future live prompts |

Example patch:

```json
{
  "display_name": "Asha",
  "custom_instructions": "Use practical examples and explain unfamiliar terms.",
  "conversation_mode": "interview_practice",
  "memory_enabled": true
}
```

Modes are backend-owned text templates. English practice requests constructive corrections and one practice question at a time; interview practice requests concise feedback and forbids inventing qualifications. Mode selection cannot create tools, change budgets, or grant permissions. Display name, custom instructions, goals, and memory text are serialized as labeled lower-trust JSON after application rules. This is a prompt boundary, not a guarantee that a model will never follow adversarial text; authorization and accounting remain enforced by code.

Ordinary preference edits apply to subsequently created conversations. Existing records retain their profile snapshot, so an already-created conversation can intentionally use the old name, goal, style, or custom instructions. Clearing a profile field does not erase that field from historical conversation snapshots. Memory changes use stricter revocation rules described below.

## Memory API and consent

All endpoints require the normal bearer session and derive ownership from it. Clients cannot submit `user_id`, system authority, or a provider resume handle.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | /api/v1/users/me/memories | List owned facts and consent status |
| POST | /api/v1/users/me/memories | Create a fact after opt-in |
| GET | /api/v1/users/me/memories/{id} | Read one owned fact |
| PUT | /api/v1/users/me/memories/{id} | Replace content/priority with an expected version |
| DELETE | /api/v1/users/me/memories/{id} | Physically delete one owned fact |
| DELETE | /api/v1/users/me/memories | Physically delete all owned facts; idempotent |

Create example:

```json
{"key":"learning_goal","content":"I am learning Kotlin for Android interviews.","priority":80}
```

Keys contain lowercase ASCII letters, digits, and underscores, starting with a letter, and are at most 64 characters. Content is trimmed, nonblank, and at most 500 characters. Priority is between 0 and 100. Keys are unique per user. The default quota is 20 facts per account; quota checks and all memory writes serialize on the user's preferences row so concurrent requests cannot exceed it.

The response contains the memory UUID and version, starting at 1. To edit it:

```json
{"content":"I am practising Kotlin interview answers.","priority":90,"expected_version":1}
```

Successful edits increment the version. A stale expected version returns `memory_version_conflict` instead of silently overwriting another device's change. Missing and foreign IDs both return `memory_not_found`.

Creation and replacement require `memory_enabled=true`. Listing and deletion work while disabled, so users can inspect and erase stored facts without opting back in. Disabling memory stops its use but retains saved rows; DELETE is the separate erase operation. The model cannot save or delete facts through speech in this phase. Only an authenticated API write changes memory, and the prompt tells the model not to claim otherwise.

## Snapshots without duplicating fact text

New conversation records use `personalization_version=1`. Their preference snapshot contains the selected mode and profile fields plus this form of memory manifest:

```json
{"enabled":true,"revision":3,"items":[{"id":"MEMORY_UUID","version":1,"content_hash":"SHA256"}]}
```

Memory content and keys are not copied into conversation JSON, reports, or logs. The manifest and normal configuration fingerprint identify exactly which saved facts were selected. At admission, the backend checks current consent, the profile's memory revision, ownership, item versions, content hashes, and the current configured memory prompt budget. Only then does it load fact text into the in-memory provider prompt.

If a fact changed or the budget became smaller, the backend rejects the pending start with `conversation_memory_changed` or `conversation_memory_budget_changed`. The transaction rolls back the claim and no allowance reservation/provider connection is created. Create a new conversation to use current context.

Historical manifest IDs/hashes remain after fact deletion, but contain no copy of fact text. Physical deletion removes the application's live database row; it does not erase database backups or retract text already sent to Gemini. Profile custom instructions and goals remain governed by their separate conversation-snapshot behavior.

## Revocation and live sessions

Every memory addition, edit, deletion, clear, or consent change increments `memory_revision`. Any change invalidates previously created memory-enabled conversations, even if the changed fact was not among their selected items. This intentionally simple rule makes context changes predictable.

After a committed change, the local session registry immediately signals affected memory-enabled runtimes to stop with `memory_changed`. Provider cleanup and Phase 5 settlement then run normally. The stop signal is prompt; connection shutdown still follows bounded I/O cleanup. A new conversation is required to use revised context.

Memory validity is also checked before socket reattachment, when entering active/reconnecting state, and in the normal lease heartbeat. This detects committed changes made through another process or operator path when the revision is updated there. A database outage cannot extend a lease; existing lease-loss behavior still fails closed. Direct operator SQL that changes facts must also increment the owner's memory revision; supported API writes do this automatically.

Disabling memory or deleting facts does not stop a conversation whose snapshot never enabled memory, because no saved facts were included there. Memory-enabled Gemini resumption uses the same already-composed prompt only while its revision remains valid. The local, single-worker pilot and global one-runtime cap remain unchanged.

## Database and migration

`0004_personalization_memory` adds five preference columns and the `user_memories` table. Memory rows have an owner foreign key with cascade deletion, a unique owner/key constraint, nonblank content/version/priority constraints, and an owner/priority index. Revision and mode constraints protect preference state. Deletion is allowed only on the memory table for the runtime role; prompt versions, user administrator updates, and migration history remain protected.

Stop the old backend, then:

```powershell
.\scripts\migrate.ps1
# Reapply scripts/database_grants.sql as the database owner.
.\scripts\run.ps1
```

No new package is required. Existing users receive empty personalization fields, general mode, and memory disabled. Old conversation snapshots retain the legacy prompt composer and are not rewritten or re-fingerprinted. Downgrading removes memory and new profile fields; it is destructive for those fields and should not be used as an ordinary deployment step.

Settings:

```env
MEMORY_MAX_ITEMS=20
MEMORY_PROMPT_MAX_ITEMS=5
MEMORY_PROMPT_MAX_BYTES=1800
```

Reducing a stored-fact quota does not silently delete existing rows; they remain listable/deletable up to the supported hard cap of 100. New creation is blocked until below the configured quota. Reducing the prompt budget can invalidate a pending conversation if its selected set no longer fits.

## Verification and limits

Run `scripts/check.ps1`. Tests cover opt-in, ownership, version conflicts, bounded Unicode selection, quotas, profile snapshots, legacy compatibility, absence of fact text in historical records/reports, admission rollback, local and heartbeat revocation, least-privilege runtime access, and PostgreSQL concurrent quota checks. Provider tests are simulated and incur no Gemini charges.

Verified: the full PostgreSQL 18 run passed 127 Python tests and all 11 JavaScript tests, plus syntax/dependency checks. The SQLite full run passed 120 with four PostgreSQL-only skips; follow-up personalization/prompt checks passed 22 with one skip after adding reduced-budget and detached-revocation coverage. Python compilation passed. The upstream Starlette/httpx test-client deprecation warning remains.

This phase implements explicit user-managed facts. It does not extract facts from audio, store transcripts, generate summaries, use semantic retrieval, infer sensitive attributes, or add external tools. It does not implement account deletion, backup deletion, encryption/key management, a production retention job, or a Kotlin memory UI. The memory table stores user-provided text under the application's existing database access controls. Additional prompt text can increase Live API token usage even though no extra model call is made. Real Gemini memory behavior, prompt-injection resistance, English/Hindi quality, cost, and latency still require credentialed device testing. Phase 5's estimated-dollar guard remains disabled pending billing calibration.
