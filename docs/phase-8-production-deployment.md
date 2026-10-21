# Phase 8: single-instance production deployment

This phase prepares a deployable closed pilot. It adds a Linux container, a Caddy HTTPS proxy, production settings, abuse bounds, operator provisioning, health checks, drain controls, operational counters, and backup/restore tooling. It does not purchase a server, change DNS, publish an endpoint, or make paid Gemini calls.

The existing runtime supports **one worker, one application instance, and one active voice conversation at a time**. The ten-session planning target is not an implemented capacity claim. This deployment does not add Redis, Kubernetes, a vector service, or a second model. It can reuse an existing TLS-enabled PostgreSQL database. Actual host, database, network, domain and model costs depend on the chosen infrastructure; no monthly price is promised.

## Architecture and files

```mermaid
flowchart LR
    K[Kotlin client] <-->|HTTPS / WSS :443| P[Caddy proxy]
    P <-->|Private Docker network| A[FastAPI single worker]
    A <-->|Verified database TLS| D[(Existing PostgreSQL)]
    A <-->|Gemini Live TLS| G[Gemini Live]
    O[Explicit operator job] -->|Owner connection| D
    B[Backup host with libpq service] -->|Dump / restore drill| D
```

`Dockerfile` builds the backend without the browser assets or tests. Dependencies use `deploy/requirements.txt` constrained by the existing lock; the server explicitly uses asyncio/h11 and the bounded WebSocket implementation. The image runs as UID/GID 10001 with a read-only root filesystem, a small temporary filesystem, dropped capabilities, and process/memory limits in Compose. Only Caddy publishes ports. The API has no host port mapping.

`deploy/compose.yaml` separates API and operator secrets. The API receives only `database_url` and `gemini_api_key`; the opt-in `operator` service receives only `migration_database_url`. Migrations never run automatically when an API process starts. No database schema change is needed for Phase 8; the head remains `0005_knowledge_tools`.

`deploy/Caddyfile` handles HTTPS certificates, HTTP redirects and WebSocket upgrades. Caddy is assigned `172.30.8.2`; Uvicorn trusts forwarded headers from exactly that address. The API address is `172.30.8.3`. If this subnet conflicts with your host/VPN, change the Compose subnet, both addresses, the Dockerfile trusted-proxy argument, and the corresponding deployment test together. Do not change the trust list to `*` or publish port 8000.

## Production configuration

Local operation stays unchanged by default. `ENVIRONMENT=production` requires:

- A nonempty backend Gemini credential and PostgreSQL runtime URL.
- `PUBLIC_ORIGIN` as one HTTPS origin, with no path, credentials, query, fragment, or wildcard. Compose derives it from `VOICE_DOMAIN`.
- An explicit PostgreSQL host/user/database and `?ssl=verify-full`. Use the certificate's DNS name. This asyncpg parameter verifies the server certificate and hostname; `ssl=require` alone is not accepted. The provided image assumes a database CA trusted by the container. Install a provider-specific CA through a reviewed image/mount setup if needed; do not disable verification.
- No migration/owner URL in the runtime process.
- `REGISTRATION_ENABLED=false`, `ENABLE_API_DOCS=false`, `ENABLE_TEST_HARNESS=false`, and `SAVE_REPORTS=false`.

Secret values are read using Pydantic file-secret support when `VOICEAGENT_SECRETS_DIR=/run/secrets`. Secret names match setting names case-insensitively. Environment values have higher precedence, so do not add credential environment overrides. The container does not contain your local `.env`; `.dockerignore` excludes credentials, virtual environments, test data, backups and reports from the build context.

The runtime refuses startup if the database migration head is wrong. Liveness remains separate from readiness. Deployments must preserve the dedicated runtime database role and the grants in `scripts/database_grants.sql`; configuration validation alone cannot determine a role's actual privileges.

## First deployment on a Linux Docker host

Prerequisites: a host with Docker Engine and Compose v2, a domain you control, outbound Gemini/database access, an existing PostgreSQL database with verified TLS, and a secure operator workstation. Use the Phase 3 instructions to create the database owner and the `voiceagent_app` runtime role. Permit inbound 80/443 and restricted operator SSH; do not expose the API, PostgreSQL, or the Docker daemon publicly. Configure a private/firewalled database path where available. Avoid another CDN/proxy in front until its forwarded-header trust is explicitly designed and tested.

From the repository root on that host:

```sh
cp deploy/.env.example deploy/.env
mkdir -p deploy/secrets
chmod 700 deploy/secrets
```

Edit `deploy/.env` with the real domain, certificate contact, model and a unique image release tag. Configure the domain's A/AAAA records to the host; publish AAAA only if IPv6 actually reaches it. DNS and certificate issuance are operator steps, not performed by this repository.

Using a secure editor/secret provisioning system, create these files with one value each:

| File | Content |
| --- | --- |
| `deploy/secrets/database_url` | `postgresql+asyncpg://voiceagent_app:URL_ENCODED_PASSWORD@db.example.com:5432/voiceagent?ssl=verify-full` |
| `deploy/secrets/gemini_api_key` | Backend-only Gemini API key |
| `deploy/secrets/migration_database_url` | Separate database owner URL, also configured with verified TLS |

Do not place real values in commands, source control, screenshots, or build arguments. With rootful Linux Docker, make the mounted files readable by UID 10001 and no other unprivileged account:

```sh
sudo chown 10001:10001 deploy/secrets/database_url deploy/secrets/gemini_api_key deploy/secrets/migration_database_url
sudo chmod 400 deploy/secrets/database_url deploy/secrets/gemini_api_key deploy/secrets/migration_database_url
```

Compose file secrets are host-file mounts, not encrypted secret storage. Source-file ownership matters: Compose `uid`/`gid` remapping is not relied on. Rootless Docker uses host UID mappings; adapt ownership and verify readability as the container's user before release. Restrict host directory access and disk/backups separately. Keep the owner secret only while running operator tasks, and remove it from the deployment host afterward if your process allows secure reprovisioning.

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml build --pull api
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm operator
```

The last command explicitly applies migrations using the operator connection. Apply the updated runtime grants as the database owner using a protected libpq service file:

```sh
psql 'service=voiceagent_owner' -X --set=ON_ERROR_STOP=1 --file scripts/database_grants.sql
```

Build a uniquely tagged image per release. The Python base tag and proxy version are development defaults: resolve and record image digests for release, scan the resulting image, and retain the previous tested image. The Linux image build has not been executed in the current Windows environment because Docker is unavailable.

Provision at least one pilot account before exposing the service:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm operator python -m scripts.manage_users --email pilot@example.com
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm operator python -m scripts.manage_admin --email pilot@example.com grant
```

Account creation prompts twice for the password and never accepts a password command-line option. The second action grants administrator privileges and is optional for ordinary users. Public registration stays disabled: this phase is a closed pilot, without email verification, account recovery, invitations, or a public signup product.

Validate the proxy before starting it, then start the runtime:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d api proxy
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

Caddy waits for API readiness before its initial start. Certificate state persists in `caddy_data`/`caddy_config`; keep those volumes through upgrades. Do not use `docker compose down -v` as a release procedure. A health check marking a container unhealthy is an alert condition; Compose restart policies do not automatically heal a live unhealthy process.

## Transport and abuse controls

Production HTTP requests require an HTTPS scope, with only loopback `/health` and `/health/ready` probes exempted. WebSockets require WSS. A supplied Origin must exactly match `PUBLIC_ORIGIN`; Kotlin can omit Origin. Host checks allow the configured hostname plus loopback health hosts. CORS is not enabled. Bearer tokens still authenticate every API request and socket attachment; HTTPS/origin checks do not grant identity.

Caddy overwrites untrusted forwarded headers by default, and Uvicorn only accepts them from the dedicated proxy address. Tests cover both accepted trusted headers and rejected direct spoofing. Changing this boundary requires retesting. Do not put tokens in URLs. The Kotlin client must use the HTTPS API and WSS socket, validate server certificates normally, and follow the existing protocol v3 start/auth flow.

HTTP bodies are limited to 32 KiB by the proxy and runtime. Runtime buffering also enforces the limit for chunked or missing-length bodies before handlers/password work, with a five-second body deadline. WebSocket frame size is 8192 bytes with a server queue of eight, plus the existing smaller application audio/control bounds. Uvicorn's HTTP concurrency threshold is 64; WebSocket admission is bounded separately by the application's protected inflight limit. Neither setting is a voice-session capacity promise.

Production auth routes and WebSocket admission use shared process-local fixed windows:

| Setting | Default |
| --- | --- |
| `AUTH_REQUESTS_PER_MINUTE` | 10 per client address |
| `AUTH_GLOBAL_REQUESTS_PER_MINUTE` | 60 across all addresses |
| `AUTH_MAX_INFLIGHT` | 4 concurrent protected operations/connections |

Limits reject before database/password work with HTTP 429 and `Retry-After: 60`, or pre-accept WebSocket denial. Trailing-slash redirects also consume requests. Windows reset after 60 seconds; bursts at a boundary can reach two windows' allowance. Successful logins count too. A WebSocket occupies its protected inflight slot for its connection lifetime. Counters reset on process restart and are not shared across workers. NAT users share an address budget. This bounded pilot protection does not replace host/network denial-of-service controls or a future distributed policy.

## Health, monitoring and logs

| Endpoint | Access and purpose |
| --- | --- |
| `GET /health` | Public liveness; no provider request or database query |
| `GET /health/ready` | Public bounded database/migration readiness; 503 while draining/closing |
| `GET /api/v1/admin/operations` | Administrator-only uptime, aggregate HTTP counts/errors/rejections/mean duration, active sessions, drain state |
| `POST /api/v1/admin/drain` | Administrator-only stop accepting new live runtimes |

Operational counters are aggregate, in RAM, and reset on restart. The operations response includes the current monitoring request in the inflight count. Session reports and existing admin usage APIs retain metadata measurements and cautious estimated cost accounting.

Production HTTP logs contain only a fixed event name, status and elapsed milliseconds. They exclude paths, queries, IPs, headers, identities and bodies. Uvicorn access logs and Caddy access logs are disabled; Docker logs rotate at 10 MiB with three files per service. Operational errors and certificate/server failures can still appear in component logs. Do not enable debug, SQL parameter logging, request-body capture, or a third-party logging integration without reviewing redaction and retention.

Monitor external HTTPS readiness, container restarts/unhealthy state, 5xx and rejection rates, session end reasons, database pool/connection usage, database/storage capacity, backup age, certificate expiry, and Gemini billing/quota independently. Alerts and destinations depend on your monitoring account and are not connected automatically. No paid observability agent is required by this deployment.

## Drain, release and rollback

1. Keep the previous image digest and configuration. Run tests and build/scan the candidate image before touching the active service.
2. As an authenticated administrator, send `POST /api/v1/admin/drain` over HTTPS. Do not put your bearer token in a command-line URL or logs. Readiness becomes 503. Existing voice sessions and their permitted reconnects continue; new voice runtime admission returns `server_draining` before reserving allowance.
3. Wait for `active_sessions` to reach zero, bounded by the existing session maximum and reconnect grace. Drain is in memory and intentionally has no public reset endpoint. Restart clears it.
4. Back up the database and verify the recovery path. Stop the old API before migrations; this repository does not promise mixed-version compatibility.
5. Explicitly run the candidate operator migration, apply grants as needed, update the release image tag/digest, and recreate the API. Verify readiness before resuming pilot use. Reload/recreate Caddy separately only when its configuration/image changes; this can disconnect WebSockets.

Uvicorn's ten-second graceful shutdown allowance and Compose's 75-second stop budget leave time for registry cleanup and bounded report settlement. Unexpected termination can still lose an in-progress provider checkpoint; expired database leases are recovered conservatively. Deploying another instance cannot resume RAM-only provider state.

If no incompatible schema migration occurred, drain/stop the candidate, select the previous tested image, and restart it. Phase 8 adds no migration. If schema/data changed incompatibly, recover into a separate database from a tested backup and make an explicit operator cutover. Do not automatically downgrade schema or restore over the live database. Single-host releases have downtime; this is not a zero-downtime or high-availability deployment.

## Backups and restore drills

Install PostgreSQL client tools at least as new as the source server. Configure protected `.pg_service.conf` and `.pgpass` files (or provider-managed equivalents) on a trusted backup host. Use distinct `voiceagent_backup` and `voiceagent_restore_drill` services; the restore service must point to a freshly created, disposable database. Use `sslmode=verify-full` in libpq service files and a trusted CA. These are libpq names, whereas the application's SQLAlchemy/asyncpg URL uses `ssl=verify-full`.

`scripts/database_backup.py` accepts service names, not credential URLs. It removes ambient connection overrides, creates uniquely named custom-format archives with private file permissions, and removes only its newly created partial output on failure. It does not delete older backups. Create and protect an output directory first:

```sh
python -m scripts.database_backup backup --service voiceagent_backup --directory /secure-backups/voiceagent
python -m scripts.database_backup verify --archive /secure-backups/voiceagent/ARCHIVE.dump
python -m scripts.database_backup restore --service voiceagent_restore_drill --archive /secure-backups/voiceagent/ARCHIVE.dump --confirm-empty-target
```

The verify action checks archive readability, not recoverability. Restore checks that the target has no user tables/views/sequences, then runs a single-transaction restore without cleaning existing objects or restoring source ownership/grants. Provision target roles and reapply runtime grants separately. Restore only trusted operator-created archives: PostgreSQL archives can contain executable database definitions. Keep concurrent writers away from the disposable restore target.

After a drill, verify migration head, expected reference/account counts, representative content, authentication and ownership APIs, then record elapsed recovery time. A real local PostgreSQL 18 drill verified the complete current schema and a synthetic knowledge row, and verified that a second restore into the populated target is rejected. That does not establish recovery time for your production data size.

Schedule backups outside the application (for example a host timer), encrypt them, copy them off-host, monitor failures/age, and set retention appropriate to user-data policy. Pilot planning targets are a daily backup interval and a one-hour restore goal; they are not achieved service guarantees. pg_dump alone provides no point-in-time recovery. Enable provider/WAL-based recovery if a daily recovery point is insufficient. User credentials, memories and private knowledge are in the database, so dumps are sensitive. Volume snapshots on the same server do not substitute for off-host recovery.

## Verification and remaining rollout work

Automated checks cover production configuration rejection, file secrets, HTTPS/WSS/origin/host boundaries, trusted proxy behavior, disabled public surfaces, auth/body bounds, private logging, administrator drain behavior, backup safety guards, and deployment-file invariants. SQLite and PostgreSQL regression suites exercise existing authentication, voice relay, knowledge, costs and recovery. Caddy's official binary accepted the proxy configuration. The Windows reconnect test also now checks clock continuity without assuming simulated work crosses a coarse monotonic-clock tick.

Docker is not installed in the current workspace: image build, Compose engine startup, real secret mount permissions, public certificate issuance, external database TLS and a live Gemini call have **not** been verified here. Run those checks on the target Docker host before exposing pilot accounts. Verify bounded shutdown while a real voice call is active, source/tool cancellation if enabled, billing behavior, and a backup drill using your actual database configuration. This phase supplies deployment artifacts and controls; rollout remains an explicit operator action.

References: [Uvicorn deployment](https://www.uvicorn.org/deployment/), [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [Caddy request-body limits](https://caddyserver.com/docs/caddyfile/directives/request_body), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/), [asyncpg TLS options](https://magicstack.github.io/asyncpg/current/api/index.html), [PostgreSQL connection services](https://www.postgresql.org/docs/current/libpq-pgservice.html), [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html), and [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html).
