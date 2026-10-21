# Phase 2 — Gemini feasibility prototype

Historical Phase 2 baseline. The current backend adds required authentication and persistence in Phase 3; follow [the Phase 3 guide](phase-3-foundation.md) for setup and the replacement WebSocket start message. The audio and measurement design below remains relevant.

Implementation date: 16 October 2026.

Status: prototype implemented and covered by offline tests. Live account access, microphone quality, audible latency, and actual billing have not been verified. No Gemini credential was configured during implementation.

## Scope

A single-process, local-only FastAPI relay connects one test client to one Gemini Live session. The browser client is a temporary audio test harness; the eventual app remains Kotlin. There is no production authentication, database, payment system, memory, daily allowance, or automatic reconnection. A provider GoAway ends the session explicitly; resumption belongs to Phase 4.

The configured baseline is `gemini-3.8-live` on the Gemini Developer API using `v1beta`. This follows the current official SDK guide, but availability must be confirmed using your account. There is no silent model fallback. `GEMINI_MODEL` and `GEMINI_API_VERSION` are environment settings.

Sources checked on 16 October 2026:

- [SDK guide](https://ai.google.dev/gemini-api/docs/live-api/get-started-sdk)
- [Audio and interruption capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Session lifecycle and limits](https://ai.google.dev/gemini-api/docs/live-api/session-management)
- [Billing and context guidance](https://ai.google.dev/gemini-api/docs/live-api/best-practices)
- [Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Python SDK implementation](https://github.com/googleapis/python-genai)

## Run on Windows

From the repository directory:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env` locally and set `GEMINI_API_KEY` to your own Gemini Developer API key. Keep the key out of chat, the browser, source control, and reports. Restart the backend after changing settings.

`requirements-lock.txt` records the complete dependency set installed for offline verification on Python 3.11 / Windows. Use `pip install -r requirements-lock.txt` to reproduce that environment rather than resolve dependencies afresh.

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --ws-max-size 8192 --ws-max-queue 8
```

Open http://127.0.0.1:8000 in a current Chromium browser. Select a language, optionally enter a short goal, click Start, grant microphone permission, and speak once the status says Listening. Use headphones initially. Click Stop to obtain a downloadable metadata report.

The server can start without a key; the health endpoint then reports `configured: false` and voice setup returns `missing_api_key`. Starting a configured voice session can incur provider charges.

Keep the server bound to loopback with proxy headers disabled and one worker. This prototype has local-address, Host, and browser Origin checks, but has no user authentication. Do not expose it through a tunnel or reverse proxy. Multiple workers would each have an independent admission slot.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| GEMINI_API_KEY | empty | Backend-only credential |
| GEMINI_MODEL | gemini-3.8-live | Exact selected model |
| GEMINI_API_VERSION | v1beta | Provider protocol version |
| SESSION_MAX_SECONDS | 300 | Total session bound, maximum 600 |
| SESSION_IDLE_SECONDS | 60 | No meaningful microphone activity after queued output finishes |
| PROVIDER_SETUP_SECONDS | 20 | Setup timeout |
| IO_TIMEOUT_SECONDS | 5 | Individual forwarding and cleanup timeout |
| CONTEXT_COMPRESSION | false | Optional 16,000-token trigger / 8,000-token retained-window experiment |
| SAVE_REPORTS | false | Save final metadata under ignored `reports/` directory |
| REPORTS_DIRECTORY | reports | Optional output directory; relative paths resolve from the repository root |
| USAGE_MODE | unknown | Raw samples only until event semantics are verified |

No transcript generation or audio recording is enabled. In-memory usage samples retain the latest 100 events, and relay timing retains the latest 2,048 packets. Reports disclose sample truncation. If saving reports, delete them after the pilot retention window; automated retention is not implemented in Phase 2.

The idle detector uses a simple server-side PCM amplitude threshold. It is a prototype heuristic, not speech recognition: background noise can count as activity and quiet speech may not. The hard duration limit remains independent. Pending output delays idle expiration, but does not extend the hard deadline.

## WebSocket protocol v1

Connect to `/ws/live` on the same origin. First send a text JSON object within five seconds:

```json
{"type":"start","language":"English and Hindi","goal":"Practise introducing myself"}
```

Allowed languages are `English`, `Hindi`, and `English and Hindi`. The goal is optional and limited to 500 characters. The client cannot supply application instructions, provider credentials, model settings, or tools.

Wait for `ready`, which includes the session ID, model, audio formats, protocol version, and duration limit. Then send raw binary mono PCM16 little-endian audio at 16 kHz. Normal frames are 640 bytes / 20 ms; nonempty frames up to 3,200 bytes / 100 ms are accepted. No WAV headers, compressed audio, JSON base64, or MediaRecorder blobs.

The server sends raw binary mono PCM16 at 24 kHz. It sends JSON control messages between audio frames:

| Event | Meaning |
| --- | --- |
| ready | Provider confirmed setup; microphone upload may begin |
| interrupted | Immediately stop and discard scheduled assistant audio |
| turn_complete | Model turn ended; this does not prove all scheduled audio was heard |
| ended | Session terminated; includes final metadata report |
| error | Admission or initial-message failure, with a safe error code |

Client control messages are exactly `{"type":"stop"}` and `{"type":"audio_end"}`. The latter signals a paused audio stream; the browser harness streams continuously and does not need it. Stop ends the entire session. Other controls terminate the session as invalid.

The server discards queued response audio when interrupted. The client also stops all scheduled playback sources. A packet already in network transit cannot be recalled; the interruption control flushes the client once received. Queue count, queued audio duration, and send timeouts bound slow-client exposure. Input backpressure ends the session instead of accumulating stale microphone audio.

The SDK `receive()` iterator completes at a model turn, so the adapter starts a new iterator for subsequent turns. Task cancellation and provider context cleanup run on stop, disconnect, setup failure, invalid messages, slow connections, idle expiration, and the hard deadline.

## Prompts

`app/prompts/system.py` and `app/services/prompt_builder.py` owns the versioned application instructions. The start message supplies only validated language and goal fields, serialized as lower-trust user preferences. Profiles are not stored. The model receives the composed instructions once at session setup.

## Measurements and cost

Reports include connected duration, provider-ready latency, input/generated audio duration, turn and interruption counts, sampled upload relay p95, selected model, prompt version, compression setting, and provider usage samples. Generated audio duration includes audio later discarded by interruption; it does not represent audible playback time.

Response and barge-in latency at the user's ear are not claimed. They need audio/device instrumentation in the later Kotlin client. Relay p95 measures receipt through completion of the upstream send, including queue wait; it does not include model inference or Android playback.

Provider usage-event aggregation is not conclusively specified by the inspected response-field documentation. The default `USAGE_MODE=unknown` therefore leaves cost and aggregated tokens null and preserves token samples. Before enabling an estimate, inspect a short multi-turn live run and reconcile the samples with provider usage/billing:

- `per_response`: sum the token categories of each report only if each report is independently billable and not a repeated snapshot.
- `cumulative`: subtract the last observed category counters only if reports are monotonic session totals. Falling counters invalidate the estimate.
- `unknown`: retain measurements without inventing a total.

The rate table covers `gemini-3.8-live` and `gemini-3.1-flash-live-preview`, using Developer API standard prices checked on 16 October 2026: text input $0.75, audio input $3.00, text output $4.50, audio output $12.00 per million tokens. Unknown models or incomplete/unsupported usage categories yield no dollar estimate. Additional thinking/cache/tool usage also invalidates the simple estimate. This estimator does not implement a spending cap and is not an invoice.

Model cost is not equivalent to raw streamed audio seconds. Retained context can be billed on later turns. Recheck pricing and model-specific listening behavior before a paid experiment. Backend hosting costs are excluded from model estimates.

## Manual feasibility benchmarks

Keep `SAVE_REPORTS=true` for disconnect tests, since a disconnected browser cannot receive the final report. Reports contain metadata, not conversation content.

| Scenario | Procedure | Record |
| --- | --- | --- |
| Short baseline | 5 minutes, about 10 turns, 2 minutes user speech, 2 minutes assistant speech, pauses, 2 interruptions, 1 language switch | Report plus manual speech-quality observations |
| Long session | Set limit to 600; repeat a 10-minute multi-turn conversation | Later-turn usage, total cost if verified, stability |
| Idle | Connect and remain silent | Idle end reason and closed upstream connection |
| Interrupted response | Speak during a longer assistant reply | Audible stop, discarded queued audio, ability to continue |
| Abrupt client loss | Close the tab during output or setup | Saved report, released slot, next session can start |
| Second client | Start another tab while one is active | `session_busy`; no second provider session |
| Provider failure | Use an unavailable model in a temporary local configuration | Safe failure, released slot, no raw SDK error exposed |
| Compression comparison | Repeat a similar long conversation with compression enabled | Quality and measured cost compared with baseline |

Use the Phase 1 response/quality targets for assessment. Keep device, network, model, configuration, usage mode, and scenario consistent when comparing. Model-generated speech and turn counts can differ between runs.

Compare reports saved into one scenario directory:

```powershell
.\venv\Scripts\python.exe scripts\summarize_benchmarks.py reports
```

Do not mix different scenarios/configurations and interpret the mean as a controlled benchmark. Missing cost estimates are never counted as zero.

## Verification

Offline checks:

```powershell
.\venv\Scripts\python.exe -m pytest -q
node --test tests\javascript\audio-worklet.test.cjs
node --check tools\voice_client\client.js
node --check tools\voice_client\capture-worklet.js
.\venv\Scripts\python.exe -m pip check
```

The tests use a simulated provider and the installed SDK's actual message models. They verify forwarding, multi-turn receiving, interruptions, queue bounds, safe setup failures, timeouts, admission, input validation, usage aggregation modes, provider cleanup, and PCM packet encoding. They make no paid API calls and do not establish real model availability or microphone quality.

Recorded verification after restructuring on Python 3.11.4 / Windows: 35 Python tests passed, 3 Node audio-worklet tests passed, both JavaScript syntax checks passed, and `pip check` reported no broken requirements. The Python run emitted one upstream Starlette/httpx test-client deprecation warning. Browser microphone playback and credentialed Gemini access remain untested.

Phase 2 implementation is ready for credentialed feasibility testing. Live benchmark results remain pending; proceed to the production backend foundation only after reviewing the quality, latency, and billing evidence.
