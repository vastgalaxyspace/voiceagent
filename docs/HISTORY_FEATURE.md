# Voice conversation history

Implemented for the Kotlin Android app and Python backend. New voice sessions
request Gemini input and output transcription alongside native audio. No separate
speech recognition service is required.

## User experience

- History displays conversations with at least one saved, nonempty user message.
- Failed connection attempts, empty VAD events and greeting-only calls stay out of
  the normal list. Their internal session records remain available for diagnostics.
- Cards show the first user message as a shortened title/preview, local date/time,
  message count and an incomplete-history indicator when needed.
- Opening a card displays ordered You/Aura bubbles, selectable transcript text,
  interrupted/partial state, retry controls and message pagination.
- More > Session diagnostics opens the previous report screen.
- More > Delete conversation requires confirmation and deletes a completed/failed
  session and its messages. Active sessions must finish first. This operation does
  not refund already accounted daily usage.
- Previous sessions cannot acquire transcripts retroactively. No old records are
  removed by the migration.

## Database

Migration: `0006_conversation_history` (after `0005_knowledge_tools`).

`conversations` gains `title`, `preview`, `message_count`, `last_message_at`,
`has_user_message`, and `transcript_status`. Existing rows default to unavailable.

`conversation_messages` stores `id`, `conversation_id`, `sequence`, `role`, `text`,
`state`, `revision`, `created_at`, `updated_at`, and nullable `completed_at`.

Message ID is stable across revisions and database retries. The unique constraint
on `(conversation_id, sequence)` prevents duplicate logical rows. Text equality
is never used to suppress separate spoken messages. Messages have a cascading
foreign key to conversations. Every API verifies the signed-in owner.

Checkpoint writes lock the live conversation row and require its runtime owner
and unexpired lease. A background writer coalesces updates roughly every 350 ms;
database work never runs in the provider audio receive loop. Retries reuse IDs
and revisions. Unconfirmed writes remain pending and are retried. Shutdown allows
up to 12 seconds to flush and marks incomplete saving as partial when finalization
can still update the database. Expired runtime recovery also marks history partial.

Pending state is bounded to 512 logical message slots and 32,000 characters per
message. Exceeding these protective bounds marks history incomplete; it does not
terminate audio. A crash can lose text received since the last committed checkpoint.

## HTTP API

### Existing session creation

`POST /api/v1/conversations`

Request remains `{ "goal": "...", "use_tools": false }`. Response adds History
metadata; existing fields remain. No transcript rows are inserted by creation.

### User History list

`GET /api/v1/conversations?view=history&limit=20&offset=0`

Returns `{ "items": [...], "next_offset": null | integer }`. Each item contains:
`id`, `title`, `preview`, `created_at`, `last_message_at`, `message_count`,
`transcript_status`, `status`. Newest creation first; limit 1–100. Only sessions
with persisted user text appear. The lightweight response excludes preference
snapshots, configuration and reports. Omitting `view` preserves the original
session-list response for existing clients.

### Metadata

`GET /api/v1/conversations/{id}`

Existing response plus History metadata. Transcript states: `unavailable`,
`available`, `partial`. Message states: `partial`, `complete`, `interrupted`.

### Messages

`GET /api/v1/conversations/{id}/messages?after_sequence=0&limit=50`

Returns `conversation_id`, `transcript_status`, `items`, `next_sequence`.
Each item contains all persisted message fields. Sort ascending by sequence;
sequences may have gaps because empty speech slots are not saved. For the next
page, use the returned `next_sequence` as `after_sequence`; null means no further
page at the time of the request. To reconcile revisions after reconnect, fetch
again from sequence zero and merge by ID/revision; an after-sequence-only fetch
cannot recover edits to earlier partial messages.

### Deletion

`DELETE /api/v1/conversations/{id}`

204 on success. 409 `conversation_still_active` unless status is ended/failed.
404 `conversation_not_found` for both missing and foreign-owned IDs. Database
messages and reservations cascade; daily aggregate usage remains. Optional local
debug report/audio files are operational artifacts and are not managed by this API.

### Existing diagnostics and stopping

`GET /api/v1/conversations/{id}/report` stays the diagnostics endpoint.
`POST /api/v1/conversations/{id}/stop` retains its request/response contract;
normal finalization now flushes transcript state as well.

## WebSocket additions

Existing `/ws/live`, protocol version 3, PCM audio and controls remain compatible.

`transcript` event: full current message text, not a text delta for the phone.
Fields: `type`, `id`, `message_id` (same as id), `conversation_id`, `sequence`,
`role`, `text`, `state`, `revision`, ISO timestamps. Replace a bubble with the same
ID only if the revision is at least the current revision.

`transcript_saved` event: `conversation_id`, `message_id`, `revision`. Acknowledge
only that revision or older; a newer live revision is not yet confirmed saved.

Caption updates are coalesced and can be omitted under audio backpressure or
disconnection. The messages HTTP endpoint is the durable source. The Android
screen refreshes while a session runs and reconciles after resumption. Clients
must not replay saved text into Gemini merely to recover History.

Input and output streams are tracked separately. Speech activity reserves the user
sequence before a delayed transcript arrives; assistant audio reserves its sequence
before its transcription. Input `finished` and provider turn boundaries complete
messages. Provider interruptions preserve a partial assistant response with state
interrupted. Text fragments follow Gemini's delta semantics. Provider events without
stable source identifiers cannot be perfectly deduplicated across arbitrary provider
replay; database retries and transport/UI duplicates are idempotent by ID/revision.

Output transcription represents generated speech. During interruption it may
include words that had not finished playing on the phone. The UI discloses this for
incomplete history. Session resumption keeps the same collector and message IDs.

## Running the update

1. Apply migrations with `venv\Scripts\python.exe -m alembic upgrade head`.
2. As the database owner, apply `scripts/database_grants.sql`; the runtime role
   needs SELECT/INSERT/UPDATE/DELETE on `conversation_messages` and DELETE on
   `conversations`. The configured local database has already received these grants.
3. Restart the backend using your normal command.
4. Install the newly built Android debug APK.
5. Speak in a new conversation, finish, then open History.

No backend process is started by this feature's deployment steps. Transcript text
is now saved for new sessions; the History screen informs the user of this behavior.

## Verification performed

- Python compilation and application import.
- Full migration into an isolated SQLite database and SQLAlchemy schema comparison.
- In-memory transcript/API smoke checks: delayed input text, interrupted output,
  intentional repeated words, idempotent saves, empty-session filtering, ownership,
  pagination, active-delete rejection and cascade deletion.
- Android `:app:assembleDebug` with installed Java 21, offline dependencies.
- Applied migration 0006 to the configured PostgreSQL database.
- Verified runtime SELECT/INSERT/UPDATE/DELETE on transcripts and DELETE on
  conversations after applying the required owner grants; database readiness passes.
- Existing Gemini, session-recovery and usage regressions: 43 passed, 2 skipped.
- Late input fragments after turn completion update the same saved message slot;
  repeated caption updates remain coalesced within the bounded audio outbox.

No new Python test cases were added. One existing Gemini configuration expectation
was updated because input transcription is intentionally enabled now. Real phone
microphone/speaker behavior still requires a new conversation on the installed app.
