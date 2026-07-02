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

## Quick verification

```powershell
curl.exe -s http://127.0.0.1:8080/health                     # traffic engine
curl.exe -s http://127.0.0.1:5001/api/health                 # backend
curl.exe -s http://127.0.0.1:5001/api/debug/full-snapshot    # needs UNOC_DEV_FEATURES=1
curl.exe -s http://127.0.0.1:5001/api/ipam/pools             # IPAM
curl.exe -s http://127.0.0.1:5001/api/devices/olt1/interfaces # interfaces (seeded device)
```

## Shutdown

Stop backend/engine/frontend processes (Ctrl+C or stop the background
processes), then:

```powershell
docker compose stop postgres
```
