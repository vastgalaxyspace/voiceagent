# Voice Agent

An Android voice conversation application planned with Kotlin, a FastAPI backend, and Gemini Live.

## Current phase

Phase 8: single-instance production deployment configuration implemented. Includes an HTTPS proxy, a non-root container, file-mounted runtime secrets, strict production settings, bounded authentication/body requests, health checks, administrator drain controls, and backup/restore tooling. Deployment has not been published. The estimated-spend guard remains disabled until live Gemini billing calibration.

Phase 5 follow-up fixes preserve spend reservations for unfinished/unreported turns and drain database maintenance safely during shutdown. Reports distinguish observed partial cost from a complete reported estimate.

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

Windows convenience commands (from the project root):

```powershell
.\scripts\run.ps1
.\scripts\check.ps1
```

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
