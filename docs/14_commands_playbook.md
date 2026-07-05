# 14. Commands Playbook

This playbook lists current local commands for the Python/FastAPI + Go services + Vue stack.

For the verified end-to-end startup guide, prefer [local_start.md](local_start.md).

## 1. Stack context

- Backend: Python/FastAPI, SQLModel/SQLAlchemy, PostgreSQL.
- Frontend: Vue 3 + Pinia + D3 in `unoc-frontend-v2/`.
- Services: Go traffic engine on `:8080`; optional Go gRPC helpers on `:50051-50054`.
- Realtime: backend WebSocket endpoint under `/api/ws`.

## 2. One-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd unoc-frontend-v2
npm ci
cd ..
```

Build Go service binaries when needed:

```powershell
cd engine-go
go build -o bin/traffic-engine.exe ./cmd/traffic-engine/
go build -o bin/optical-service.exe ./cmd/optical-service/
go build -o bin/batch-service.exe ./cmd/batch-service/
go build -o bin/status-service.exe ./cmd/status-service/
go build -o bin/port-summary-service.exe ./cmd/port-summary-service/
cd ..
```

## 3. Local start

Preferred logged start:

```powershell
.\scripts\start-stack-logged.ps1 -IncludeOptionalGoServices
.\scripts\status-stack.ps1
```

Manual start order is documented in [local_start.md](local_start.md):

1. PostgreSQL
2. Go traffic engine
3. FastAPI backend
4. Vue/Vite frontend
5. Optional Go gRPC helpers

## 4. Health checks

```powershell
curl.exe -s http://127.0.0.1:8080/health
curl.exe -s http://127.0.0.1:5001/api/health
curl.exe -s http://127.0.0.1:5001/api/debug/full-snapshot
```

The debug snapshot requires `UNOC_DEV_FEATURES=1` on the backend.

## 5. Quality checks

Backend compile check:

```powershell
python -m compileall backend
```

Frontend type check:

```powershell
cd unoc-frontend-v2
npm run type-check
cd ..
```

Focused backend tests should use the audit venv when local dependencies differ:

```powershell
.\.venv-audit\Scripts\python.exe -m pytest backend/tests/test_dependency_resolver_cache.py
```

## 6. Performance harness

Reusable L3 recompute micro-benchmark:

```bash
export PYTHONPATH=.
DATABASE_URL="sqlite:///bench_l3.db" BENCH_N=200 .venv-audit/Scripts/python.exe backend/tests/perf/bench_l3_recompute.py
rm -f bench_l3.db
```

See [performance.md](performance.md) for scope and measured results.

## 7. Shutdown

```powershell
.\scripts\stop-stack.ps1 -DryRun
.\scripts\stop-stack.ps1
```

Use `-Force` only after reviewing `-DryRun` output.
