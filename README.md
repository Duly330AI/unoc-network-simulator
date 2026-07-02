# UNOC v3 - Network Emulator

A full-stack network planning and emulation tool built with Node.js, Express, Prisma, React, React Flow, and Socket.io.

## Features

- Network topology canvas (drag & drop devices)
- Backend-persisted topology via Prisma + SQLite
- Port-aware link provisioning
- Real-time updates with Socket.io
- Basic simulation metrics (`device:metrics`, `device:status`)

## Stack

- Frontend: React 19, Vite, React Flow, Tailwind
- Backend: Node.js, Express, Socket.io
- Data: Prisma + SQLite (dev)

## Getting Started

1. Install dependencies
```bash
npm install
```

2. Create environment file
```bash
cp .env.example .env
```

3. Sync Prisma client and database
```bash
npx prisma generate
npx prisma db push
```

4. Start development server
```bash
npm run dev
```

Application runs at `http://localhost:3000`.

## Recovered Stack Quick Start

For the stabilized recovered FastAPI/Vue UNOC stack, use the verified guide in [docs/local_start.md](docs/local_start.md). Recovery status and known test drift are tracked in [RECOVERY_STATUS.md](RECOVERY_STATUS.md).

Start the recovered stack in this order:

1. `./scripts/start-postgres.ps1`
2. `./scripts/start-engine.ps1`
3. `./scripts/start-backend.ps1`
4. `./scripts/start-frontend.ps1`

Recovered stack ports:

| Service | Port |
| --- | --- |
| Frontend | `http://127.0.0.1:5173` |
| Backend | `5001` |
| Traffic Engine | `8080` |
| PostgreSQL | `5432` |

The Go Traffic Engine on `:8080` is required for this recovered stack. The backend expects it to be available during startup. `UNOC_DEV_FEATURES=1` enables the Debug Viewer and development debug endpoints, and `UNOC_DISABLE_RELOAD=1` avoids reload noise during local recovery/dev runs. The `unoc` / `unocpw` database values in `.env.example` are Docker Compose development defaults only.

VLAN is intentionally out of scope for this stabilization and remains future work.

## Verification

```bash
npm run lint
npm test
npm run build
```

## Docs

Architecture and domain docs are in `docs/`.
