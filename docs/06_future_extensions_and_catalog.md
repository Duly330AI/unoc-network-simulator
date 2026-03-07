# 06. Future Extensions and Catalog

This document defines deferred tracks, the hardware/optical catalog contract, and deterministic realtime simulation behavior.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow

## 1. Deferred Scope and Non-Goals

Initial deferred tracks:
- Networking: dual-stack IPv6, multi-backbone domains, advanced path caching
- UI: lasso selection, bulk override UI, additional dashboards
- Persistence: deprovision reclamation workflows, historical metric persistence
- Simulation: per-flow QoS, latency/queueing models, advanced congestion models
- Diagnostics: path conflict analyzer, long-term override audit log
- Security: AuthN/AuthZ, RBAC, multi-tenant boundaries
- Performance: 10k+ scale optimization and advanced event batching

Policy:
- Deferred items stay explicitly tracked in roadmap (`DEFERRED` status).
- Deferred does not allow undocumented behavior drift in implemented MVP flows.

## 2. Hardware and Optical Catalog

The catalog is the authoritative versioned source for default device characteristics (for example `tx_power_dbm`, `sensitivity_min_dbm`, `insertion_loss_db`, default capacities/ports).

## 2.1 Goals

- Preserve vendor/model baseline authenticity
- Deterministic defaults for provisioning/runtime
- Controlled override mechanism without mutating base artifacts
- Reproducibility via schema version + hash integrity

## 2.2 Filesystem Layout

```text
data/catalog/
  hardware/
    olt/*.json
    ont/*.json
    passive/*.json
    active/*.json
  manifest.json
  overrides/
    ... (optional, mirrors structure)
```

`manifest.json` must define:
- `schema_version`
- explicit file list
- sha256 per file

## 2.3 Catalog Entry Shape

```json
{
  "catalog_id": "OLT_HUAWEI_MA5800_X2_V1",
  "device_type": "OLT",
  "vendor": "Huawei",
  "model": "MA5800-X2",
  "version": "1.0",
  "attributes": {
    "tx_power_dbm": 5.0,
    "sensitivity_min_dbm": -30.0,
    "insertion_loss_db": 3.5,
    "capacity_mbps": 40000
  },
  "meta": {
    "source": "datasheet-2024-05",
    "notes": "baseline"
  }
}
```

Notes:
- `tx_power_dbm`: OLT classes
- `sensitivity_min_dbm`: ONT-like classes
- `insertion_loss_db`: passive inline/splitter classes
- `capacity_mbps`: optional by class/policy

## 2.4 Load and Validation Pipeline

Startup pipeline:
1. read manifest
2. validate `schema_version`
3. verify sha256 integrity for all listed files
4. parse + schema-validate entries
5. build indexes (`by_catalog_id`, `by_device_type`, `by_vendor_model`)
6. load overrides and merge with allow-list rules
7. compute consolidated `catalog_hash`
8. freeze in-memory catalog structures

Failure policy:
- integrity/schema failures block startup in strict mode
- optional degraded/dev mode may continue with explicit warning and safe fallback defaults

## 2.5 Override Merge Rules

Allowed mutable fields:
- `tx_power_dbm`
- `sensitivity_min_dbm`
- `insertion_loss_db`
- class-specific numeric defaults explicitly whitelisted by schema

Immutable fields:
- `catalog_id`
- `device_type`
- `vendor`
- `model`
- `version`

Reject override when:
- unknown `catalog_id`
- forbidden field change attempted
- type mismatch or invalid value range

## 2.6 Catalog Service Interface

Backend service surface:

```ts
getModel(catalogId): CatalogEntry | null
listModels(filter): CatalogEntry[]
defaultTxPower(oltCatalogId): number | null
defaultSensitivity(ontCatalogId): number | null
defaultInsertionLoss(passiveCatalogId): number | null
listFiberTypes(): FiberType[]
computeCatalogHash(): string
```

## 2.7 API Endpoints

- `GET /api/catalog/hardware?type=...`
- `GET /api/catalog/hardware/:catalog_id`
- `GET /api/optical/fiber-types`

Contract notes:
- endpoint output must be deterministic (stable sort order)
- pagination optional but response shape must be versioned if introduced

## 2.8 Provisioning and Runtime Integration

Defaults resolution order:
1. explicit device-level value
2. catalog model default (via `catalog_id` reference)
3. system fallback default

On provision:
- store effective optical/runtime fields used at provisioning time
- keep catalog linkage (`catalog_id`/`hardware_model_id`)
- mark `modified_from_catalog=true` when device value deviates from model default

Behavior implication:
- changing catalog defaults affects only devices that do not have explicit per-device overrides for that field.

## 2.9 Determinism, Testing, Observability

Determinism:
- log `catalog_hash` and `schema_version` at startup
- stable output ordering by `catalog_id`

Minimum tests:
- valid catalog load path
- override merge path
- hash stability
- provisioning default resolution
- immutable field protection

Observability:
- logs: entry counts, override diff summary, startup integrity result
- metrics: `catalog_entries_total{type}`, `catalog_load_failures_total`

## 3. Realtime Simulation and Metrics

Simulation is deterministic, periodic, and delta-based for live UI updates.

## 3.1 Goals and Non-Goals (MVP)

Goals:
- deterministic leaf traffic generation
- hierarchical upstream aggregation
- utilization computation with over-capacity visibility
- delta event emission plus snapshot recovery

Non-goals:
- historical storage in MVP
- per-flow QoS and latency modeling
- smoothing/EMA in MVP baseline

## 3.2 Metrics Model

Per device metric shape:
- `upstream_traffic_gbps`
- `downstream_traffic_gbps` (MVP can be symmetric)
- `utilization_percent` (can exceed 100)
- `capacity_gbps` (snapshot and/or contract-specific)
- `tick_seq` (global monotonic runtime tick)
- `version` (entity-local metric version)

Passive/container-only nodes may omit utilization where not applicable.

## 3.3 Leaf Generation Rules

Eligible leaves:
- `ONT`, `BUSINESS_ONT`, `AON_CPE`
- provisioned and effectively online

Modes:
- `variable`: deterministic pseudo-random factor by `(seed, device_id, tick_seq)`
- `percent`: fixed fraction of configured maximum

MVP behavior:
- smoothing disabled
- downstream may mirror upstream unless per-direction model is enabled

## 3.4 Aggregation and Utilization

- Build immutable topology snapshot at tick start.
- Aggregate post-order from leaves toward upstream/core.
- Offline leaves contribute zero.
- `utilization_percent = upstream / capacity * 100`.
- Values above `100%` remain unclamped.
- Division by zero or missing capacity => utilization `null` with warning logs.

## 3.5 Scheduler and Tick Engine

Config keys:
- `TRAFFIC_ENABLED`
- `TRAFFIC_TICK_INTERVAL_SEC`
- `STRICT_ONT_ONLINE_ONLY`
- `TRAFFIC_RANDOM_SEED`

Loop behavior:
- run tick
- sleep remaining interval
- graceful shutdown support

Persistence note:
- `tick_seq` is process-local in MVP and resets on restart.

## 3.6 Runtime Structures

```text
metrics_by_device: Map<deviceId, Metrics>
last_tick_seq: number
last_emitted_snapshot: Map<deviceId, MetricsView>
```

Threading/runtime policy:
- computation on snapshot copy
- short critical section for state swap

## 3.7 Diff Emission and Backpressure

Change criteria per device:
- absolute metric delta above epsilon
- utilization bucket boundary crossed
- first seen version

Emit batch delta event:

```json
{
  "event": "deviceMetricsUpdated",
  "tick": 123,
  "items": [{ "id": "...", "up_gbps": 1.2, "down_gbps": 1.2, "utilization_percent": 62.0, "version": 10 }]
}
```

Ordering guidance:
- topology/optical/status updates first
- metrics updates after status stabilization

Backpressure:
- if output queue is saturated, collapse queued metric updates to latest tick snapshot (drop intermediate metric ticks only).

## 3.8 Reconnect and Snapshot Recovery

Required endpoint:
- `GET /api/metrics/snapshot`

Snapshot response includes:
- current tick
- per-device metrics map
- capacity fields required by UI contracts

Client behavior:
- on reconnect or `topo_version` gap, refresh topology + metrics snapshots and replace local baselines before resuming delta processing.

## 3.9 Link Metrics (Phase 2)

Deferred track:
- per-link utilization and throughput snapshots/events
- needs efficient path-accounting model to avoid O(links * leaves) blowups

## 3.10 PRNG Determinism

- Use deterministic seeded generator (e.g. xor-shift/PCG)
- Seed material: `TRAFFIC_RANDOM_SEED + device_id + tick_seq`
- Identical inputs must produce identical traffic series

## 3.11 Observability and Resilience

Metrics:
- `unoc_sim_tick_duration_seconds`
- `unoc_sim_changed_devices`
- `unoc_sim_active_leaves`
- `unoc_sim_skipped_ticks_total`

Health:
- `GET /api/sim/status` -> `{ enabled, interval_sec, last_tick_ts, tick_seq }`

Resilience:
- tick exceptions are logged and counted; engine continues
- negative generated traffic clamped to zero with warning
- no-leaf fast path allowed while preserving tick monotonicity

## 4. Deferred Architecture Tracks

Explicit deferred tracks:
- Physics layout engine hardening (beyond MVP)
- Ring protection/failover simulation
- Remote signed catalog bundles
- Multi-catalog version negotiation
- Catalog diff API

## 5. Cross-Document Contract

- `04_signal_budget_and_overrides.md`: optical defaults and fiber types
- `05_realtime_and_ui_model.md`: socket contract and UI consumption rules
- `11_traffic_engine_and_congestion.md`: congestion semantics and thresholds
- `13_api_reference.md`: canonical API/event definitions
