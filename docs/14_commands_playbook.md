# 14. Commands Playbook

This playbook lists operational commands for setup, development, testing, quality checks, and performance runs.

Stack context:
- Node.js + TypeScript (`tsx`)
- Express + Prisma
- Vite client build pipeline

## 1. Prerequisites

Required locally:
- Node.js (project-compatible modern LTS)
- npm
- SQLite for local DB file workflows (or configured external DB)

Optional for perf load tests:
- `artillery` (used by `npm run perf:load`)

## 2. Environment Setup

## 2.1 Install Dependencies

```bash
npm install
```

## 2.2 Environment Variables

Create `.env` (for example from `.env.example`) and define at minimum:
- `DATABASE_URL`

Optional/feature-specific:
- `GEMINI_API_KEY`
- `APP_URL`
- simulation/perf flags as required by runtime

## 2.3 Prisma Bootstrap

```bash
npx prisma generate
npx prisma db push
```

Optional DB inspection:

```bash
npx prisma studio
```

## 3. Development Commands

## 3.1 Run App in Development Mode

```bash
npm run dev
```

Current script:
- `node --import tsx server.ts`

Behavior:
- starts backend runtime and serves frontend through configured dev integration
- local URL is environment/runtime dependent (do not hardcode docs to one host/port)

## 3.2 Clean Build Artifacts

```bash
npm run clean
```

## 4. Test and Quality Commands

## 4.1 Run Full Test Suite

```bash
npm test
```

## 4.2 Run Smoke Tests Only

```bash
npm run test:smoke
```

## 4.3 Type/Lint Check

```bash
npm run lint
```

## 4.4 Production Build

```bash
npm run build
```

## 4.5 Preview Built Client

```bash
npm run preview
```

## 5. Performance Harness Commands

## 5.1 Seed Benchmark Dataset

```bash
npm run perf:seed
```

Current script target:
- `tsx server/scripts/perf-seed.ts`

## 5.2 Execute Load Scenario

```bash
npm run perf:load
```

Current script target:
- `artillery run perf/load-test.yml`

## 6. Recommended Local Run Order

```bash
npm install
npx prisma generate
npx prisma db push
npm run dev
```

Before merge/release checks:

```bash
npm run lint
npm test
npm run build
```

## 7. Troubleshooting Quick Notes

- Prisma/client mismatch after dependency updates:
  - rerun `npx prisma generate`
- DB schema drift in local dev:
  - rerun `npx prisma db push` on intended target DB
- Perf load command fails:
  - verify `artillery` availability and `perf/load-test.yml` presence

## 8. CI Mapping

Minimum CI gates map to:
- `npm run lint`
- `npm test`
- `npm run build`

Performance scripts are optional in baseline CI and can run in dedicated perf profiles.

## 9. Cross-Document Contract

- `12_testing_and_performance_harness.md`: quality/perf strategy and gates
- `13_api_reference.md`: API surface validated by tests and load scenarios
- `ARCHITECTURE.md`: component/service context for commands
