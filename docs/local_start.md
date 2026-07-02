# Local Start Guide (verified 2026-07-02)

Exact, reproducible startup for local development on Windows (PowerShell).
Every command below was verified end-to-end during the recovery run audit
(see [RECOVERY_STATUS.md](../RECOVERY_STATUS.md)).

## Required toolchain

| Tool   | Verified version | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| Docker | 28.x             | PostgreSQL container only        |
| Python | 3.13.x           | FastAPI backend (venv)           |
| Node   | 22.x / npm 11.x  | Vue 3 frontend (`unoc-frontend-v2`) |
| Go     | 1.25.x           | engine-go services (build once)  |

## Services and ports

| Service                    | Port  | Required? |
| -------------------------- | ----- | --------- |
| Frontend (Vite dev server) | 5173  | yes (UI)  |
| FastAPI backend            | 5001  | yes       |
| Go Traffic Engine (HTTP)   | 8080  | **yes — backend refuses to start without it** |
| PostgreSQL (docker)        | 5432  | yes (shared by backend + traffic engine) |
| Go optical service (gRPC)  | 50051 | optional (Python fallback) |
| Go batch service (gRPC)    | 50052 | optional (Python fallback) |
| Go status service (gRPC)   | 50053 | optional (Python fallback) |
| Go port summary service (gRPC) | 50054 | optional (Python fallback/degrade) |

Start order: **postgres → traffic-engine → backend → frontend**.

## 0) One-time setup

```powershell
# Python venv + dependencies
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Frontend dependencies
cd unoc-frontend-v2
npm ci
cd ..

# Build Go services (traffic-engine is mandatory)
cd engine-go
go build -o bin/traffic-engine.exe ./cmd/traffic-engine/
go build -o bin/optical-service.exe ./cmd/optical-service/   # optional
go build -o bin/batch-service.exe ./cmd/batch-service/       # optional
go build -o bin/status-service.exe ./cmd/status-service/     # optional
go build -o bin/port-summary-service.exe ./cmd/port-summary-service/ # optional
cd ..

# Environment file
Copy-Item .env.example .env   # defaults match the docker compose Postgres
```

## 1) PostgreSQL

```powershell
docker compose up -d postgres
```

Only the `postgres` service is needed for development. `prometheus`/`grafana`
in the same compose file are optional monitoring.

First run only — create schema and minimal seed data (safe on a fresh DB):

```powershell
$env:DATABASE_URL = 'postgresql://unoc:unocpw@localhost:5432/unocdb'
.\.venv\Scripts\python.exe scripts\reset_dev_db.py --force --seed --demo-topology
```

## 2) Go Traffic Engine (mandatory)

```powershell
cd engine-go
.\bin\traffic-engine.exe
```

- Listens on `http://localhost:8080`; its `DATABASE_URL` default matches the
  compose Postgres, so no env var is needed.
- **Why mandatory:** `backend/services/traffic/v2_runner.py` connects to the
  engine at import time and raises `RuntimeError` if it is unreachable
  (the Python traffic fallback was removed for performance). Health check:
  `GET http://localhost:8080/health`.

## 3) FastAPI backend

```powershell
$env:DATABASE_URL = 'postgresql://unoc:unocpw@localhost:5432/unocdb'  # or use .env
$env:UNOC_DEV_FEATURES = '1'
$env:UNOC_DISABLE_RELOAD = '1'
.\.venv\Scripts\python.exe run.py    # http://127.0.0.1:5001
```

Environment flags:

- `UNOC_DEV_FEATURES=1` — enables the dev-only debug endpoints
  (`/api/debug/full-snapshot`, `/api/debug/status-diagnostics`, …) and thereby
  the **Debug tab** in the frontend. Without it those routes return 404 and the
  UI hides/blocks the Debug view.
- `UNOC_DISABLE_RELOAD=1` — turns off uvicorn auto-reload. Recommended when
  running as a background process; omit it if you want reload-on-change during
  active development.

## 4) Frontend (unoc-frontend-v2)

```powershell
cd unoc-frontend-v2
npx vite --host 127.0.0.1 --port 5173 --strictPort
```

Open **http://127.0.0.1:5173**. The Vite dev server proxies `/api` (including
WebSocket) to `http://localhost:5001`. Binding to `127.0.0.1` explicitly avoids
an IPv6-only (`::1`) bind that breaks IPv4 tooling.

## Helper scripts

The same four steps are wrapped in `scripts/start-postgres.ps1`,
`scripts/start-engine.ps1`, `scripts/start-backend.ps1`,
`scripts/start-frontend.ps1` (thin wrappers, no destructive operations).

Use `scripts/status-stack.ps1` to inspect the local stack before starting more
processes. It reports the expected ports, listener PIDs, process names, command
lines when available, work-copy matches, and read-only HTTP health checks.

## Logged background start

For agent-friendly local debugging, start the stack in the background with
stdout/stderr logs and PID files under `logs/`:

```powershell
.\scripts\start-stack-logged.ps1
```

The helper starts Compose Postgres, then starts the traffic engine, backend, and
frontend only when their expected ports are free. If a service is already
listening, it prints the owning PID/process details instead of starting a
duplicate. Use `scripts/status-stack.ps1` to inspect running services and
`scripts/stop-stack.ps1` for controlled shutdown.

To also start the optional Go/gRPC helper services with logs:

```powershell
.\scripts\start-stack-logged.ps1 -IncludeOptionalGoServices
```

This adds Optical PathFinder (`50051`), Batch Operations (`50052`), Status
Propagation (`50053`), and Port Summary (`50054`). These services are optional
because the backend can fall back or degrade when they are unavailable, but
starting them reduces startup degraded-mode warnings and makes their logs
available under `logs/`.

## Quick verification

```powershell
curl.exe -s http://127.0.0.1:8080/health                     # traffic engine
curl.exe -s http://127.0.0.1:5001/api/health                 # backend
curl.exe -s http://127.0.0.1:5001/api/debug/full-snapshot    # needs UNOC_DEV_FEATURES=1
curl.exe -s http://127.0.0.1:5001/api/ipam/pools             # IPAM
curl.exe -s http://127.0.0.1:5001/api/devices/olt1/interfaces # interfaces (seeded device)
```

## Shutdown

For a safe preview of what would be stopped:

```powershell
.\scripts\stop-stack.ps1 -DryRun
```

For controlled shutdown:

```powershell
.\scripts\stop-stack.ps1
```

The shutdown helper runs `docker compose stop postgres` for the Postgres
service only. For the engine, backend, and frontend ports it inspects listener
PIDs and command lines, asks before stopping matched local processes, and skips
unknown port owners instead of blindly killing by port. Use `-Force` only when
you have already reviewed the targets, for example after `-DryRun`.

Manual shutdown is also fine: stop backend/engine/frontend processes (Ctrl+C or
stop the background processes), then:

```powershell
docker compose stop postgres
```
