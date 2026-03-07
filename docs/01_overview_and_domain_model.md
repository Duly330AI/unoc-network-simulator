# 01. Overview and Domain Model

UNOC v3 models a fiber/access topology (FTTH) with active and passive devices, container nodes (POP/CORE_SITE), links, optical propagation, provisioning-driven IPAM, admin overrides, and realtime deltas.

This document is adapted for the AI Studio stack used in this repository:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow
- Realtime: WebSocket delta events (no full-topology rebroadcast after bootstrap)

Guiding principles:
- API-first and type-synchronized contracts.
- Deterministic operations (allocation, ordering, propagation).
- Minimal deltas for realtime updates.
- Clear separation between design docs and execution tracking.

## 1.1 Implementation Status Baseline (Feature-Complete Target)

This section captures required feature scope from the previous spec baseline and maps it to the current AI Studio architecture. It is intentionally inclusive (no feature cuts).

### A) L2/L3 fallback pipeline
- Required capability:
  - Logical graph traversal is primary.
  - If no passable upstream path exists, forwarding fallback must synthesize continuity.
- AI Studio mapping:
  - Traffic/forwarding services in backend TypeScript modules.
  - Shared passability check used by dependency + traffic + status services.

### B) IPAM (lazy, deterministic)
- Required pools and defaults:
  - `core_mgmt` -> `10.250.0.0/24`
  - `ont_mgmt` -> `10.250.1.0/24`
  - `aon_mgmt` -> `10.250.2.0/24`
  - `cpe_mgmt` -> `10.250.3.0/24`
  - `olt_mgmt` -> `10.250.4.0/24`
  - `noc_tools` -> `10.250.10.0/24`
- Additional required pool:
  - Router-to-router p2p `/31` pool (pending until implemented).
- Allocation rules:
  - At provisioning time.
  - Idempotent and deterministic.
  - Concurrency-safe.

### C) Provisioning matrix and strict dependency checks
- Strict-by-default behavior.
- Parent/container invariants and upstream dependency checks are mandatory.
- Optical recompute hook is triggered on relevant mutations.

### D) Link rules
- Support typed link rules including logical uplink variants.
- Optical attenuation must exclude non-optical link categories.
- Logical upstream graph must still include those links for dependency/traffic.

### E) Status service and passability
- Centralized status evaluation with precedence rules.
- Admin overrides win.
- Effective link status and passability normalization are shared across services.

### F) Realtime transport quality
- Bounded/coalescing outbox queue.
- Single async dispatcher.
- Heartbeat/ping-pong cleanup for stale connections.
- Coalesced per-device status/optical events under burst.

### G) UI/Details and live data surfaces
- Ports summary and ONT list endpoints.
- Details tabs: Overview | Interfaces | Optical.
- Interfaces and addresses fetch-on-demand.

### H) Hardware model selection at create-time
- Device creation supports hardware catalog choice.
- Selection drives default interfaces/capacities.
- Safe default for headless/test flows.

### I) Admin overrides and DEGRADED propagation
- Device and Link PATCH override endpoints.
- Passive nodes can become `DEGRADED` on upstream loss.
- Frontend explicitly distinguishes `DEGRADED` in visuals.

### J) Tariff technology and defaults
- Tariff model includes technology marker (`GPON`/`AON`).
- Deterministic default assignment for leaf device classes.
- UI filters tariff choices by inferred technology.

### K) Effective capacity fields (API contract)
- `GET /api/devices` exposes effective capacity in both:
  - `parameters.capacity.effective_device_capacity_mbps`
  - `parameters.effective_capacity_mbps`
- Router cockpit requirement:
  - compact total capacity line with current/max rendering rules.

## 2. Domain Model and Classification

## 2.1 Core Entities
- Device: active, passive_inline, passive_container, or always-online logical root.
- Interface: role-based network attachment (`management`, `p2p_uplink`, `access`, `optical`).
- Link: typed connection between interfaces.
- IPPool/Allocation: provisioning-time address assignment.
- ProvisioningRecord: optional audit track.

## 2.2 Device Classification Table (Canonical)

| Device Type | Role Class | Provisioning Allowed | Container? | Always Online? | Hosts Children | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Backbone Gateway | special | implicit root | no | yes | no | Root anchor and upstream baseline |
| Core Router | active | yes | no | no | limited | Requires backbone association |
| Edge Router | active | yes | no | no | no | Routed p2p participant |
| OLT | active | yes | no | no | no | Optical origin |
| AON Switch | active | yes | no | no | no | Active aggregation |
| POP | passive_container | no | yes | yes | yes | Hosts active children |
| CORE_SITE | passive_container | no | yes | yes | yes | Top-level site container |
| ODF | passive_inline | no | no | no | no | Optical distribution frame |
| NVT | passive_inline | no | no | no | no | Passive termination |
| Splitter | passive_inline | no | no | no | no | Optical split loss element |
| HOP | passive_inline | no | no | no | no | Generic passive path element |
| ONT | active edge | yes | no | no | no | Optical endpoint |
| Business ONT | active edge | yes | no | no | no | ONT variant |
| AON CPE | active edge | yes | no | no | no | CPE with distinct mgmt pool |

## 2.3 Key Relationships
- POP and CORE_SITE are physical grouping boundaries.
- Containers are not link endpoints.
- Containers host active devices via parent container relation.
- Containers are aggregation sinks for traffic views, but not optical path participants.
- Active-passive-active chains form full optical paths.

## 2.4 Optical and Signal Attributes

| Entity | Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- | --- |
| OLT | `tx_power_dbm` | float | yes | +5.0 | Launch power |
| ONT/Business ONT | `sensitivity_min_dbm` | float | yes | -30.0 | Minimum acceptable Rx |
| ODF/NVT/HOP | `insertion_loss_db` | float | yes | ODF/HOP 0.5, NVT 0.1 | Passive loss |
| Splitter | `insertion_loss_db` | float | yes | 3.5 | Split loss |
| Link | `length_km` | float | yes | context default | Fiber length |
| Link | `physical_medium_id` | FK | yes | auto-select | Medium profile |
| Link (derived) | `link_loss_db` | computed | n/a | n/a | `length_km * attenuation_per_km` |

Constraints:
- `tx_power_dbm` sanity range configurable (default envelope: -10..+10).
- `sensitivity_min_dbm` envelope typically -33..-26.
- `insertion_loss_db >= 0`.
- `length_km >= 0`.
- `attenuation_per_km > 0`.
- `physical_medium_id` must reference an existing medium.

Mutation behavior:
- PATCH updates to optical fields trigger affected ONT recompute.
- Fiber constants available via `/api/optical/fiber-types`.

## 2.5 Status Implications for Traffic
- ONT/Business ONT:
  - `DEGRADED` and `DOWN` block upstream generation.
- AON CPE exception:
  - may continue in `DEGRADED` under defined no-backbone fallback policy.
- Infrastructure devices:
  - `DEGRADED` can still aggregate unless admin-overridden to `DOWN`.

## 3. Contract Notes for Current Repository
- This file defines required capability scope.
- Concrete implementation and progress tracking belong in:
  - `docs/ROADMAP.md` (tasks, dependencies, logs)
  - `docs/13_api_reference.md` (public API contract)
- If implementation deviates, update both roadmap tasks and this document.
