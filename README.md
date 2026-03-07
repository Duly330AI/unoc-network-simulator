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

## Verification

```bash
npm run lint
npm test
npm run build
```

## Docs

Architecture and domain docs are in `docs/`.
