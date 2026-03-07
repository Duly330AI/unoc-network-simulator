# 03. IPAM and Status Logic

This document defines the authoritative behavior for IP allocation, effective status evaluation, passability semantics, event ordering, and observability in the current AI Studio stack.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow
- Database: SQLite/Postgres via Prisma

## 1. IPAM (Lazy Allocation)

Principle:
- No pre-allocation per device.
- Prefix pools materialize on first provisioning use.
- Allocation is deterministic and concurrency-safe.

## 1.1 Pool Definitions (Authoritative)

| Pool Key | Canonical Name | CIDR | Trigger Device Types | Purpose | Status |
| --- | --- | --- | --- | --- | --- |
| core_mgmt | management/core_infrastructure | 10.250.0.0/24 | Core Router, Edge Router (Backbone optional) | Core/router management | implemented baseline |
| olt_mgmt | management/olt | 10.250.4.0/24 | OLT | OLT management | implemented baseline |
| aon_mgmt | management/aon | 10.250.2.0/24 | AON Switch | AON switch management | implemented baseline |
| ont_mgmt | ont/ont_management | 10.250.1.0/24 (or larger by rollout decision) | ONT, Business ONT | ONT management | implemented baseline |
| cpe_mgmt | cpe/cpe_management | 10.250.3.0/24 | AON CPE | CPE management | implemented baseline |
| noc_tools | tooling/noc | 10.250.10.0/24 | NOC tooling scope | utility space | implemented baseline |
| p2p | p2p_links | /31 slices from reserved supernet | Router-to-router routed uplinks | transit point-to-point | pending track |

Notes:
- Pool keys are canonical contract identifiers.
- CIDR values can evolve via controlled migration without changing pool keys.
- Optional Backbone Gateway management allocation remains feature-flag controlled.

## 1.2 VRF and Uniqueness Model

IP uniqueness constraints:
- unique per Prefix: `(prefix_id, ip)`
- unique per VRF: `(vrf_id, ip)`

Implications:
- Global uniqueness across different VRFs is not required.
- Management allocations should live in `mgmt` VRF.
- Future transit p2p pool should use dedicated VRF (`transit` or `infrastructure`) to separate management vs routed links.

## 1.3 Allocation Rules

Management interfaces:
- Created exactly once for provisioned active devices.
- Role: `management`.
- Name convention: `mgmt0` (deterministic).

P2P uplink interfaces:
- Created in pairs when routed links are created.
- Role: `p2p_uplink`.
- `/31` deterministic assignment rule:
  - lower IP to lexicographically smaller device id.

## 1.4 Allocation Flow (Pseudocode)

```ts
async function provisionWithIpam(deviceId: string) {
  await prisma.$transaction(async (tx) => {
    const device = await tx.device.findUniqueOrThrow({ where: { id: deviceId } });

    const role = classifyPrefixRole(device.type); // core_mgmt|olt_mgmt|aon_mgmt|ont_mgmt|cpe_mgmt
    await ensureIpamDefaults(tx);

    const prefix = await findPrefixByRole(tx, role);
    const allocation = await allocateNextFreeIp(tx, prefix);

    await createManagementInterface(tx, device.id, allocation.ip, allocation.prefixLen);
    await markProvisioned(tx, device.id);
  });

  await triggerStatusPhase1(deviceId);
}
```

## 1.5 Constraints and Failure Modes

- One management interface per device.
- p2p /31 must bind to exactly two interfaces (when implemented).
- Exhaustion returns `POOL_EXHAUSTED`.
- Allocation must be race-safe under concurrent provisioning.

## 1.6 API Exposure

Current/target endpoint surface:
- `GET /api/ipam/prefixes` -> prefix objects with VRF and role metadata
- `GET /api/ipam/pools` -> pool utilization summary (`allocated_count`, `capacity`, `utilization`)
- `GET /api/devices/:deviceId/interfaces`
- `GET /api/interfaces/:interfaceId/addresses`
- `POST /api/interfaces/:interfaceId/addresses`
- `DELETE /api/interfaces/:interfaceId/addresses/:addressId`

Note:
- Addresses are interface-scoped; no global `GET /api/ipam/addresses` endpoint is required by default.

## 1.7 Extensibility

Deferred/next tracks:
- IPv6 dual-stack pools.
- IP reclamation/free-list on deprovision/delete.
- Allocation audit log and lineage.

## 2. Status Semantics (Current Target)

Status enum:
- `UP`, `DOWN`, `DEGRADED`, `BLOCKING`

Admin override precedence:
- Override (`UP`/`DOWN`/`BLOCKING`) wins over computed state.

## 2.1 Effective Status Rules

Without override:
- Always-online classes (`POP`, `CORE_SITE`, `Backbone Gateway`) report `UP` baseline; still act as dependency anchors.
- Routers (`CORE_ROUTER`, `EDGE_ROUTER`) require strict upstream L3 viability; failures -> `DOWN`.
- OLT/AON Switch require provisioned + upstream L3 viability; failures -> `DOWN`.
- ONT/Business ONT/AON CPE require provisioned + signal/upstream viability; missing signal or upstream -> `DOWN`.
- Passive inline (`ODF`, `Splitter`, `NVT`, `HOP`) require both:
  - valid upstream chain to a viable L3-capable/anchor path,
  - at least one downstream terminating edge-class endpoint.
  - missing either side -> `DOWN`.

`DEGRADED` usage:
- reserved for partial evaluability/controlled transitional states or internal evaluation exceptions,
- must not mask hard dependency failures for strict classes.

## 2.2 Link Effective Status and Passability

Link status evaluation:
- Admin override takes precedence.
- Otherwise based on stored/evaluated logical state.

`is_link_passable` is authoritative traversal predicate and is shared by:
- dependency validation,
- status propagation,
- traffic simulation/path traversal.

## 2.3 Traffic Gating by Status

- Leaf generation (ONT/Business ONT/AON CPE) is suppressed when upstream viability is false.
- This prevents fictional throughput in partially broken topologies.

## 2.4 Diagnostics Contract

Per-device diagnostics payload should include:
- `upstream_l3_ok: boolean`
- `chain: string[]` (ordered path when available)
- `reason_codes: string[]` with stable machine-readable values

Example reason codes:
- `no_router_path`
- `routers_no_l3`
- `no_default_route`
- `no_mgmt_interface`
- `missing_next_hop`
- `loop_detected`
- `device_not_in_graph`
- `exception`

## 2.5 Upstream L3 Strictness and BFS Deprecation Path

Authoritative rule:
- A device may only be `UP` when its class-specific upstream viability requirements are satisfied.

Specifics:
- Routers use strict L3 trace semantics (default-route/neighbor chain validation with loop protection).
- Passive inline classes (`ODF`, `SPLITTER`, `NVT`, `HOP`) require both:
  - upstream chain ending in L3-viable path/anchor,
  - at least one downstream terminating endpoint (`ONT`, `BUSINESS_ONT`, `AON_CPE`).
- Leaf traffic generation is gated by `upstream_l3_ok`.

Deprecation note:
- Legacy BFS reachability must not be treated as authoritative status source.
- Any remaining BFS-derived heuristics are transitional and scheduled for removal in follow-up phases.

## 3. Event Ordering and Coalescing

Within one recompute/coalescing window:
1. optical/link derived updates
2. `deviceSignalUpdated`
3. `deviceStatusUpdated`

Override mutation events (`deviceOverrideChanged`) are emitted immediately.

Important distinction:
- Coalescing window tick (debounce) is not the same as traffic tick interval.

## 4. Hybrid Accelerator Track (Legacy Learnings + Optional Future)

Historical context from prior architecture included a Go status propagation microservice with Python fallback and reported significant speedups. In current AI Studio stack, treat this as optional accelerator track:
- Primary implementation remains in TypeScript service layer.
- Optional future: extract propagation engine into separate high-performance service (Go/Rust) via gRPC/HTTP.
- Hard requirement: functional fallback in main backend until confidence threshold is reached.

### 4.1 Required Guarantees if External Accelerator is used
- Automatic fallback path remains available.
- Response includes execution source (`native` vs `accelerator`) for observability.
- No behavior drift between implementations (contract tests mandatory).

### 4.2 Performance Expectations
- Define latency SLOs for:
  - single-device propagation,
  - medium batch propagation,
  - optical recompute affected-set updates.
- Enforce via benchmark CI gates, not ad-hoc manual runs.

## 5. Observability

Structured events:
- `status.evaluate.start`
- `status.evaluate.result`
- `status.propagation.start`
- `status.propagation.complete`
- `status.propagation.failure`

Metrics:
- `status_propagation_duration_ms`
- `status_propagation_affected_devices_total`
- `status_propagation_failures_total{reason}`
- `ipam_allocation_duration_ms`
- `ipam_pool_utilization{pool_key}`

## 6. Testing Baseline

Minimum mandatory tests:
- IPAM:
  - pool role mapping,
  - deterministic allocation order,
  - pool exhaustion,
  - concurrent allocation safety.
- Status:
  - strict dependency gating per device class,
  - passability alignment across status/dependency/traffic,
  - override precedence,
  - reason-code stability.
- Realtime:
  - event ordering and coalescing semantics.
- Optional accelerator:
  - native vs accelerator parity contract tests.

## 7. Cross-Document Contract

- `02_provisioning_model.md`: provisioning flow invokes IPAM + status hooks.
- `04_signal_budget_and_overrides.md`: optical/signal formulas and override semantics.
- `05_realtime_and_ui_model.md`: websocket envelope and client consumption model.
- `13_api_reference.md`: publicly exposed endpoint/event contract.
