# Context and continuation

Apply migration `0007_context_continuation` before running this version. Stop old
workers before migration. Existing sessions/history remain available. Existing
database grants already cover the new columns; no new table grants are needed.

## Continue a finished call

`POST /api/v1/conversations/{id}/continue` with `{}` creates a new owned voice
session linked to a finished/failed call. Send its returned ID to `/ws/live` as
usual. It uses current profile, consent, prompt version and allowance. It does
not resurrect an ended runtime or reuse an old allowance reservation.

The response exposes `continued_from_id`; clients can group linked calls into a
thread. The existing messages endpoint returns one call's messages. The mobile
client must implement Continue and grouping; opening History alone incurs no
provider call. At start, the server loads at most eight linked ancestors,
checking ownership, with a 12,000-byte history budget. It loads stored summaries
and recent messages not covered by the summary. Without summaries, it uses the
latest transcript text that fits. Truncation and partial transcripts are labeled.
Deleted source records are no longer loaded; deleting a source does not retract
content already sent to a live provider or spoken/copied into later transcripts.

## Summaries

Set `SUMMARY_MODEL` to a text model available to your Google project. Run a
**single** separate process:

```powershell
.\venv\Scripts\python.exe -m scripts.summarize_conversations
```

`--once` processes at most one eligible call and exits. Paid generation is opt-in:
the worker refuses to start without SUMMARY_MODEL. It scans durable database
records, retrying failures, and processes terminal calls with at least 12 saved
messages by default. Short calls use transcript fallback. Each call gets one
bounded summary (4,000 UTF-8 bytes), an exact message sequence checkpoint and
version. Input is an exact prefix bounded to 48,000 bytes; remaining messages
are eligible for continuation context. A digest comparison rejects transcript
changes during generation. Transcripts revised after call completion disable
use of the summary, falling back to messages. The worker never reads inherited
profile/memory context or promotes generated claims into saved personal facts.

There is no periodic summarization of active calls yet. Use provider sliding
window compression for the active audio window. Adding a summary to a running
session does not remove old audio tokens.

## Profile and memory

Existing `display_name`, language and custom instructions are supplied every
session. Optional user-provided `pronouns` now has an 80-character profile field.
Memory candidates are ranked by lexical overlap with the conversation goal,
then existing priority/order, and retain the existing consent, revision, five
item and 1,800-byte limits. There are no embeddings or automatic fact extraction.
Voice memory writes are not enabled: authenticated memory CRUD remains required,
and memory changes still invalidate affected live calls.

## Capacity, compression and measurements

`MAX_ACTIVE_SESSIONS` bounds each process (default 1). PostgreSQL admission uses
a transaction advisory lock and `MAX_GLOBAL_SESSIONS` (default 100) across all
processes using the database. SQLite is for tests and has no distributed cap.
The per-user active-call unique index remains. Expired leases are reclaimed by
maintenance. Route reconnects to the owning worker; shared routing/pubsub and
100-call load tests are still required before a multi-instance production rollout.

`CONTEXT_COMPRESSION=true` enables provider sliding window management with
`CONTEXT_TRIGGER_TOKENS=16000` and `CONTEXT_TARGET_TOKENS=8000`. Trigger must exceed
target. These are snapshotted for new calls. Restart after active calls finish.
The feature does not generate a persistent summary or guarantee retention of old
details. Validate quality/latency with your actual model before broad rollout.

Docker Compose exposes these settings on the API. Set SUMMARY_MODEL and start
the optional worker with `docker compose --profile summaries up -d summary-worker`.
Only one summary worker should run; duplicate workers may incur duplicate calls.

Reports include `system_prompt_bytes`. This is not a token count or a billing
estimate. `USAGE_MODE` remains unknown until calibrated using real provider
events, including reconnections. Existing time and optional cost guards remain.

## Remaining production work

Distributed reconnect routing/notifications, confirmed voice memory writes,
periodic summaries, exact total token budgeting, paid summarizer usage accounting,
provider billing calibration, and realistic 100-session load/failure tests remain
separate work. This release does not certify capacity or silently enable paid
background generation. Use a process supervisor to keep the summary worker alive.
