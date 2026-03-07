# 12. Testing and Performance Harness

This document defines the minimum quality gates, contract testing strategy, and performance harness requirements.

Stack context:
- Test runner: Node.js test framework (`node:test`) + HTTP integration tooling
- API layer: Express + Prisma
- Realtime: Socket.io

## 1. Quality Strategy

Quality pillars:
- API correctness under valid and invalid inputs
- realtime contract stability (event names, payloads, ordering)
- deterministic simulation behavior
- performance regressions detected early

Definition of green baseline:
- `npm run lint`
- `npm test`
- `npm run build`

## 2. Test Layers

## 2.1 API Smoke Tests

Mandatory smoke flow:
- create device
- create link
- fetch topology
- validate response shape and status codes

Environment:
- isolated test database per run
- deterministic seed data for reproducibility

## 2.2 API Negative and Validation Tests

Required negative suites:
- invalid link/device relations
- invalid parent/container assignments
- invalid optical parameters
- pool exhaustion / duplicate constraints

Assertions:
- HTTP status correctness
- machine-readable error code correctness
- deterministic error payload shape

## 2.3 Realtime Contract Tests

Verify:
- event name parity with reference
- payload schema per event type
- ordering guarantees inside one mutation window
- coalescing/gap behavior contracts

Include reconnect scenario:
- snapshot + delta reconciliation after disconnect

## 2.4 Simulation and Congestion Tests

Verify:
- deterministic tick generation for fixed seed/topology
- GPON aggregation correctness
- hysteresis enter/clear thresholds
- no-event on steady-state

## 2.5 UI-Contract Tests (Boundary)

Focus on contract boundaries (not full visual E2E):
- ports summary grouping behavior
- cockpit fallback behavior with partial payloads
- mapping of canonical error codes to UI-safe messages

## 3. Performance Harness

## 3.1 Seed Harness (`perf:seed`)

Purpose:
- generate reproducible large topologies for benchmarks

Requirements:
- deterministic topology generation from seed inputs
- configurable scale profile (small/medium/large)
- output metadata for run reproducibility

## 3.2 Load Harness (`perf:load`)

Purpose:
- stress API/realtime/simulation paths and record latency/throughput

Scenarios:
- topology read stress (`/api/topology`)
- mutation burst (device/link create/delete)
- metrics tick pressure + websocket consumers
- ports summary polling under load

Outputs:
- p50/p95/p99 latency
- throughput
- error rates
- dropped/coalesced event indicators

## 3.3 Performance Budgets

Baseline budgets must be versioned and enforced by CI/profile gates.

Examples:
- topology fetch p95 bound
- mutation p95 bound
- tick duration bound under target dataset

## 4. CI and Gating

Mandatory CI stages:
1. lint
2. unit/integration tests
3. build

Recommended extended stages:
- contract-test profile
- performance smoke profile
- flaky-test detection/retry report

Merge policy:
- no merge on red baseline gates
- contract drift requires explicit version/doc update

## 5. Test Data and Determinism

Rules:
- test fixtures are versioned
- random sources seeded
- snapshot tests only for stable contracts
- no hidden dependency on local machine state/timezone

## 6. Observability for Test and Perf Runs

Collect during test/perf:
- failed error-code distribution
- event ordering violations
- simulation tick duration histogram
- cache hit/miss metrics where relevant

Artifacts:
- junit/summary report
- contract diff report
- benchmark summary report

## 7. Expansion Roadmap

Next expansions:
- websocket chaos tests (reconnect, burst, reordering)
- larger synthetic datasets with scenario packs
- targeted regression suites for optical and container-heavy topologies

## 8. Cross-Document Contract

- `05_realtime_and_ui_model.md`: event ordering and gap handling
- `11_traffic_engine_and_congestion.md`: simulation and congestion logic
- `13_api_reference.md`: API/event source-of-truth for contract tests
