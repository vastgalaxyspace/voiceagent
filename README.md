# Voice Agent

For public ngrok access, start `ngrok http 8000`, then run
`.\scripts\run.ps1 -PublicOrigin https://YOUR-HOST.ngrok-free.dev`.
This selects tunnel mode, accepts remote users, and enforces HTTPS, the configured
hostname/Origin, authentication rate limits and request-size limits. Keep ngrok's
original Host/Origin; do not use the legacy header-rewrite policy. Alternatively
set `ENVIRONMENT=tunnel` and `PUBLIC_ORIGIN` in `.env`, then use `scripts/run.ps1`.
Update PUBLIC_ORIGIN whenever your tunnel URL changes. Production hosting still
uses `ENVIRONMENT=production` and the deployment runbook.

See [context management and continuation](docs/context-management.md) for migration
0007, the Continue API, optional background summaries and session-capacity settings.

An Android voice conversation application planned with Kotlin, a FastAPI backend, and Gemini Live.

## Conversation history

New voice sessions save user and Aura transcripts in PostgreSQL while audio continues
through Gemini Live. The Android History screen displays chat messages; connection
attempts and greeting-only sessions are excluded. Technical reports remain available
separately. See the [History implementation and API guide](docs/HISTORY_FEATURE.md).

Deploy with migration `0006_conversation_history`, then apply
`scripts/database_grants.sql` as the database owner before restarting the backend.
Previous sessions do not have transcripts and cannot be reconstructed.

This repository contains the backend, migrations, deployment scripts, documentation
and tests. The Android app lives in its own project. Local APKs and temporary frontend
copies under `artifacts/` are excluded from Git. Keep `.env`, database credentials,
recordings, reports, backups, virtual environments and signing keys private.

## Voice interruptions and background sound

Clients using server-side detection (including the browser and older Android builds) use automatic speech detection with interruption enabled,
low speech-start/end sensitivity, 200 ms prefix padding, and 600 ms silence duration. Tune these with
`VOICE_START_SENSITIVITY` (`low` or `high`), `VOICE_PREFIX_PADDING_MS` (0–500), and
`VOICE_SILENCE_DURATION_MS` (100–2000). These are initial trial values, not measured guarantees.
Lower sensitivity reduces accidental starts but can miss soft or very short words such as “stop”.
More confirmation delays genuine interruption; a longer silence allowance delays the reply.
The relay and browser still discard queued answer audio on every provider interruption.

`VOICE_PROACTIVE_AUDIO=false` is the default: the configured live endpoint was observed rejecting
the optional `proactivity` setup field with code 1007, preventing every voice session from starting.
Leave it disabled unless endpoint support has been verified. Explicit opt-in with `true` sends it
only for `gemini-3.8-live` with `v1beta`; other model/API combinations omit it.
Normal automatic speech detection and interruption tuning do not require proactivity.
Voice instructions are appended even to published prompts: prioritize stop/wait and
new questions, ignore irrelevant sound, and treat standalone “hmm”/“okay” as acknowledgments unless
they answer a question or confirm a choice. These instructions and proactive audio do not prevent
all VAD interruptions and cannot undo one after the provider cancels generation. Short acknowledgments,
TV, other speakers, and echo can still interrupt hands-free mode. There is no speaker identification.

The browser's **Microphone** selector defaults to **Hands-free**. Choose **Hold to talk** for a noisy
room: hold the button (pointer, Space, or Enter) while speaking, then release it. Released input is
replaced with silent PCM, so background sound is not forwarded and automatic VAD can finish the turn.
The assistant's output keeps playing. Release, pointer cancellation, focus loss, tab hiding, reconnect,
and session cleanup release the hold. Only press for intentional input; sound during a hold can still
be heard. This is a browser harness feature, not a change to the Android client or WebSocket protocol.
Echo cancellation, noise suppression, and automatic gain remain requested from the browser.

Restart the backend and refresh the browser to load the changes, then start a new conversation.
Test headphones vs speakers, silence vs clicks, a deliberate “wait”, pauses inside questions, and TV
in both microphone modes. Download the metadata report to compare `browser_interruption_events`.
Live acoustic behavior has to be checked on the actual device; simulated tests do not measure noise
rejection or interruption latency. Playback stutter without interruption events needs separate diagnosis.

## Current phase

For local testing, `CONVERSATION_CREATIONS_PER_HOUR=0` disables the hourly conversation-start
limit, including when the current window was already exhausted. Positive values re-enable it
(default 10). Restart the backend after changing this setting. Daily voice allowance, session
duration, authentication limits, and single-session admission remain independent.

Phase 8: single-instance production deployment configuration implemented. Includes an HTTPS proxy, a non-root container, file-mounted runtime secrets, strict production settings, bounded authentication/body requests, health checks, administrator drain controls, and backup/restore tooling. Deployment has not been published. The estimated-spend guard remains disabled until live Gemini billing calibration.

Phase 5 follow-up fixes preserve spend reservations for unfinished/unreported turns and drain database maintenance safely during shutdown. Reports distinguish observed partial cost from a complete reported estimate.

New conversations request one brief Gemini greeting in the preferred language. The WebSocket `ready` event advertises `greeting_pending`; checkpoint resumption never requests another greeting. Greeting input/output uses the normal usage and cost reporting.

New account passwords must contain 4–8 characters. Login continues to accept legacy passwords up to 128 characters. Existing hashes and accounts require no migration. Restart the backend after updating these Python sources; container deployments require an updated image and redeployment. Finish active conversations first because checkpoints are held in process memory.

Read the [Phase 1 specification](docs/phase-1-specification.md) for the proposed scope, architecture, cost model, acceptance targets, and decisions to revisit.

Read the [Phase 2 runbook](docs/phase-2-prototype.md) for setup, the WebSocket protocol, usage measurement, and benchmark instructions.

Read the [Phase 3 setup and API guide](docs/phase-3-foundation.md) for authentication, PostgreSQL setup, and runtime permissions. It supersedes the Phase 2 unauthenticated start flow.

Read the [Phase 4 recovery guide](docs/phase-4-reliability.md) for the current WebSocket protocol v3, retry/grace limits, lease migration, and recovery behavior. Stop the older backend before applying the new migration.

Read the [Phase 5 cost enforcement guide](docs/phase-5-cost-enforcement.md) for allowance reservation, settlement, rate limits, usage APIs, administrator setup, and safe cost-guard activation.

Read the [Phase 6 personalization and memory guide](docs/phase-6-personalization-memory.md) for opt-in, memory APIs, prompt budgets, versioning, deletion behavior, and migration. Memory management is available through `/docs`; the temporary browser remains an audio harness.

See the [folder structure guide](docs/project-structure.md) for the complete file tree, module responsibilities, and where to make changes.

Read the [Phase 7 tools and knowledge guide](docs/phase-7-tools-knowledge.md) for migration, activation, API examples, limits, source events, and security boundaries. The browser harness still starts audio-only conversations; opt into tools using the API.

Read the [Phase 8 deployment runbook](docs/phase-8-production-deployment.md) for the Linux Docker Compose setup, PostgreSQL TLS requirements, closed-pilot account provisioning, release/rollback procedures, monitoring, and backup drills. It retains one worker and one active voice conversation per instance.

Quick start on Windows: install `requirements-dev.txt` using `venv\Scripts\python.exe -m pip`, copy `.env.example` to `.env` if it does not already exist, and set your private PostgreSQL URLs and backend-only `GEMINI_API_KEY`. Apply migrations first:

```powershell
.\scripts\migrate.ps1
```

Use the Phase 3 guide to grant the runtime database role its limited permissions, then run:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --ws-max-size 8192 --ws-max-queue 8
```

Open http://127.0.0.1:8000. Create an account or sign in, use headphones, click Start, and speak after the Listening status. API documentation is at `/docs`. Keep the single-worker pilot local. Live sessions can incur provider charges.

For local audio-output debugging, set `SAVE_OUTPUT_AUDIO=true` before starting the server. Each completed assistant turn is written as a playable 24 kHz mono WAV file under `.local/output_audio`. This is disabled by default and forbidden by the production configuration because the files contain conversation audio.

Windows convenience commands (from the project root):

```powershell
.\scripts\run.ps1
.\scripts\check.ps1
```

### Using the Android app through ngrok

Local mode accepts dynamically generated tunnel Host names, so a special host-rewrite
policy is not required. Start the backend on the laptop, then start ngrok:

```powershell
.\scripts\run.ps1
ngrok http 8000
```

Copy the ngrok **HTTPS origin** into the app's backend URL field, for example
`https://example-name.ngrok-free.app`. Do not append `/docs`, `/api/v1`, or `/ws/live`;
the app adds the required paths itself. The app may run on a different phone or laptop,
but ngrok and the backend must be running on the same backend laptop.

Allowing all Host names in local mode does not remove login protection or production
security checks. The development server still binds to `127.0.0.1`, accepts the local
ngrok agent as its proxy, and production mode continues to allow only the configured
`PUBLIC_ORIGIN`. Never commit `.env`, the Gemini key, database passwords, or the ngrok
authentication token. A newly cloned laptop must create its own `.env`, install the
dependencies, apply migrations, and be able to reach its configured PostgreSQL database.

`app/` contains the backend, `tools/voice_client/` contains the temporary browser harness, and `tests/` separates unit, integration, and JavaScript tests. The ASGI entry point and existing API URLs remain unchanged.

The specification uses provisional defaults where product requirements have not yet been confirmed. Performance and cost figures are targets to validate, not measured results.

## Planned implementation sequence

1. Product and cost specification — documented.
2. Gemini feasibility prototype — implemented; live measurements pending.
3. Backend foundation — implemented; PostgreSQL setup and API guide available.
4. Reliable conversation engine — implemented; checkpoint resumption and lease recovery available.
5. Cost enforcement — implemented; live billing calibration remains pending.
6. Personalization and memory — implemented; user-managed facts with no extra model calls.
7. Optional tools and knowledge — implemented; bounded read-only retrieval, live provider validation pending.
8. Production deployment — configuration and operations implemented; Docker-host and live rollout verification pending.
9. Optimization — not started.

## Android Silero speech turns

Aura 1.4.0 requests `speech_detection: "client"` in its authenticated `/ws/live`
start message. For these sessions only, Gemini automatic activity detection is
disabled. The Android app runs Silero on echo/noise-processed 16 kHz mono PCM16,
then sends `speech_start`, binary PCM, and `speech_end` in that order. The relay
validates the sequence and forwards Gemini `activityStart` / `activityEnd`.
Clients omitting the new field retain server-side automatic detection. A resumed
connection must keep the same detection mode; capture buffers are discarded on
reconnect, mute, and talk-mode changes.

Initial Android tuning lives in `SpeechTurnGate.kt`: 512-sample (32 ms) frames,
96 ms speech confirmation while idle, 192 ms while assistant playback is active,
288 ms rolling pre-roll, and 768 ms silence before ending a turn. Silero uses
NORMAL mode while idle and AGGRESSIVE mode during playback. Hold-to-talk bypasses
the classifier, with release ending the turn immediately. Local speech starts
clear playback; provider interruptions still clear any queued output.

Install the updated APK **and restart the backend yourself** before checking this
feature. Start a new conversation, leave Hold to talk off, and compare speaker
and headphone operation. Test keyboard clicks, normal/quiet interruptions, short
"stop" utterances, and pauses within a sentence. Android Logcat tag `AuraAudio`
reports route/effect status and speech boundaries without logging microphone
content. TV dialogue remains real speech to VAD; echo suppression remains device
dependent. Tune only after checking actual false and missed interruptions.
