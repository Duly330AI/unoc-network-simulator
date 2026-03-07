# UNOC v3 Architecture Overview

This document is the high-level architecture entry point and map to the detailed specifications in `/docs`.

## 1. System Intent

UNOC v3 is a deterministic network emulation and planning platform.

Primary goals:
- authoritative backend state
- deterministic provisioning/status/optical/traffic behavior
- realtime UI synchronization through event streams
- contract-first APIs and testable operations

## 2. Architecture Principles

- Full-stack TypeScript across backend and frontend
- Backend as single source-of-truth for topology and runtime state
- Deterministic computation and ordering rules
- Event-driven updates with explicit recovery paths
- Documentation and tests as enforceable contracts

## 3. Runtime Topology

Core runtime layers:
1. Client UI (React + React Flow + Zustand)
2. REST and Socket gateways (Express + Socket.io)
3. Domain services (provisioning, status, optical, traffic, container, ports)
4. Persistence layer (Prisma + SQLite/Postgres)
5. Operational tooling (test/perf harness, command playbook)

High-level data flow:
- client issues mutations via REST
- backend validates and persists
- domain recomputes derived state
- socket events publish deltas
- clients apply deltas or resync from snapshot on gaps

## 4. Technology Stack

Frontend:
- React
- Vite
- React Flow
- Zustand

Backend:
- Node.js
- Express
- Socket.io
- Prisma

Databases:
- SQLite (local/dev/test)
- PostgreSQL (production-capable path)

## 5. Domain Service Boundaries

Core service responsibilities:
- Device service: device lifecycle and hierarchy state
- Link service: link validation and mutation
- Provisioning service: dependency checks and idempotent realization
- Status service: effective status evaluation and propagation
- Optical service: path resolution and signal budget calculations
- Traffic service: deterministic tick metrics and congestion transitions
- Ports/interfaces service: role summaries and occupancy contracts
- Catalog service: model defaults and fiber-type source-of-truth
- Event dispatcher: coalesced realtime emission and ordering guarantees

## 6. State and Contract Model

Authoritative state:
- persisted topology entities
- derived runtime fields (status/signal/metrics)

Contract surfaces:
- REST API (`/api/...`)
- Socket envelope/events
- deterministic error-code catalog

Version/recovery semantics:
- `topo_version` supports gap detection
- clients must resync topology/metrics snapshots when gaps are detected

## 7. Determinism and Ordering

Determinism expectations:
- stable role/type mapping
- stable path/segment selection tie-breakers
- stable API ordering for list responses
- deterministic simulation output for fixed seeds and inputs

Event ordering baseline:
1. topology/optical mutations
2. signal deltas
3. status deltas
4. metrics/congestion deltas

## 8. Observability and Operations

Operational pillars:
- structured logs for mutation/recompute/error paths
- metrics for simulation, cache behavior, conflict rates
- health/status endpoints for runtime components

Operational docs:
- command workflows and local runbooks in `14_commands_playbook.md`
- test/perf governance in `12_testing_and_performance_harness.md`

## 9. Documentation Map (Canonical Specs)

Core specification set:
- `01_overview_and_domain_model.md`
- `02_provisioning_model.md`
- `03_ipam_and_status.md`
- `031_IPAM-Architecture-Future.md`
- `04_links_and_batch.md`
- `04_signal_budget_and_overrides.md`
- `05_realtime_and_ui_model.md`
- `06_future_extensions_and_catalog.md`
- `07_container_model_and_ui.md`
- `08_ports.md`
- `09_cockpit_nodes.md`
- `10_interfaces_and_addresses.md`
- `11_traffic_engine_and_congestion.md`
- `12_testing_and_performance_harness.md`
- `13_api_reference.md`
- `14_commands_playbook.md`

Roadmap source-of-truth:
- `ROADMAP.md` tracks implementation tasks, dependencies, and builder logs.

## 10. Deferred Tracks and Non-Goals

Deferred architecture tracks include:
- advanced physics/layout engine
- ring protection simulation
- extended multi-catalog/version negotiation
- large-scale optimization phases

These tracks are explicitly managed as deferred roadmap tasks and are not implicit MVP scope.

## 11. Cross-Document Contract

- `ROADMAP.md`: operational implementation source-of-truth
- `13_api_reference.md`: external contract for APIs/events
- `12_testing_and_performance_harness.md`: contract enforcement strategy
- `14_commands_playbook.md`: executable command workflows
