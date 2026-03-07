# 05. Realtime and UI Model

This document defines realtime event contracts, UI interaction behavior, deterministic client synchronization, and failure semantics.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow

## 1. Realtime Delta Events

## 1.1 Event Inventory (MVP)

| Event | Payload (shape) | Trigger | Coalesce | Notes |
| --- | --- | --- | --- | --- |
| `deviceCreated` | `{ id, type, name, status }` | `POST /api/devices` | no | Initial acquisition |
| `deviceStatusUpdated` | `{ id, status, override? }` | Status recompute | yes | Drop duplicates in same tick/window |
| `deviceSignalUpdated` | `{ id, received_dbm, signal_status, margin_db? }` | Signal recompute | yes | Compact payload by default |
| `linkMetricsUpdated` | `{ tick, items:[{ id, traffic_gbps, utilization_percent, version }] }` | Traffic tick delta | yes | Emit only for changed links |
| `linkUpdated` | `{ id, length_km, physical_medium_id?, physical_medium_code?, link_loss_db }` | Optical patch | yes | Medium key maps to attenuation catalog |
| `deviceOpticalUpdated` | `{ id, insertion_loss_db?, tx_power_dbm?, sensitivity_min_dbm? }` | Optical attribute patch | yes | Passive/OLT/ONT updates |
| `linkAdded` | `{ id, a_device, b_device, type }` | `POST /api/links` | no | |
| `linkDeleted` | `{ id }` | `DELETE /api/links/:id` | no | |
| `linkStatusUpdated` | `{ id, status, override? }` | Link override / dependency change | yes | |
| `deviceOverrideChanged` | `{ id, override_status, effective_status }` | Override mutation | no | |
| `deviceContainerChanged` | `{ id, parent_container_id }` | Assignment / unassign | no | `parent_container_id` may be `null` |

## 1.2 Coalescing Strategy

Maintain an in-memory coalescing map keyed by `(event_type, id)` inside one recompute/emission window.

Rules:
- last write wins per key in current window,
- flush in deterministic event-order sequence,
- include correlation metadata for multi-step operations.

## 1.3 Socket Contract (Authoritative)

Transport:
- Socket.io namespace/path under API prefix (`/api/socket.io` in deployment; resolved by server config)
- no client-side event name translation layer

Envelope:

```json
{
  "type": "event",
  "kind": "deviceStatusUpdated",
  "payload": {},
  "topo_version": 101,
  "correlation_id": "req_...",
  "ts": "2026-03-07T12:00:00.000Z"
}
```

Contract requirements:
- `topo_version` is monotonic and allows gap detection.
- If client receives a version gap (e.g. 100 -> 102), it must trigger full topology resync.
- Heartbeat/ping-pong must be enabled by Socket.io defaults and stale clients cleaned up server-side.

## 1.4 Event Ordering Guarantees

Within one window/tick:
1. topology/optical mutation events (`linkUpdated`, `deviceOpticalUpdated`)
2. `deviceSignalUpdated`
3. `deviceStatusUpdated`
4. container/auxiliary events (`deviceContainerChanged`)

For create flows:
1. create event (`deviceCreated`/`linkAdded`)
2. derived status/signal events

## 2. UI Interaction Model

Layout:
- Header + viewer tabs
- Three-column workspace: Palette | Canvas | Context Panel

Central canvas invariant:
- Spatial state (pan/zoom/node positions/link geometry) is owned by canvas engine only.
- Cockpit components receive data updates but must not mutate geometry.
- Content overflow must be handled in component internals (truncate/wrap), never by resizing topology geometry.

## 2.1 Core Interactions

| Action | Mechanism | Backend Result | UI Feedback |
| --- | --- | --- | --- |
| Create device (single) | Drag palette -> canvas | `POST /api/devices` | Ghost -> solid on success |
| Create devices (bulk) | Context menu on palette item | Batch create workflow | Aggregated toast |
| Select | Click | `selection[]` update | Highlight |
| Multi-select | Ctrl/Cmd + click | Append selection | Combined panel |
| Start link | Context menu start | link mode | Cursor/hint change |
| Complete link | Click target | `POST /api/links` | Link flash + toast on error |
| Provision | Context panel action | `POST /api/devices/:id/provision` | Spinner -> badge |
| Multi-provision | Selection action | batch/iterative provision calls | Aggregated result |
| Assign parent POP | Selection action | parent patch endpoint | Success/failure summary |
| Edit link optical props | Link panel form | `PATCH /api/links/:id` | Inline validation |
| Edit passive loss | Device panel numeric input | `PATCH /api/devices/:id` | Debounced delta updates |
| View ONT optical analysis | ONT details panel | read API + socket deltas | Live summary + on-demand breakdown |

## 2.2 Frontend State Model

```ts
store = {
  devices: Device[],
  links: Link[],
  selection: string[],
  ui: { viewMode: "topology" },
  pending: {
    deviceCreates: Set<string>,
    linkCreates: Set<string>,
    opticalEdits: Set<string>
  }
}
```

## 2.3 Feedback Principles

- Non-blocking toasts for failures.
- Optimistic updates only where rollback is deterministic.
- Bulk operations always return a summarized outcome.
- Undo actions are short-lived and explicitly scoped to operation IDs.

## 3. Detailed Panels and Contracts

## 3.1 Bulk Device Creation Modal

Contract:
- Trigger: palette context action
- Inputs: `count` (min 1, max policy), optional naming prefix, required parent for `OLT`/`AON_SWITCH` when container policy demands it
- Accessibility: focus trap, ESC close, Enter confirm, autofocus first field
- Undo: reverse-order deletion of created IDs
- Placement: overlap-aware clustered layout, persisted through layout endpoint

## 3.2 Ports and Interfaces Summary

Endpoint:
- `GET /api/ports/summary/:device_id`

Response:

```json
{
  "device_id": "...",
  "total": 0,
  "by_role": {
    "UPLINK": { "total": 0, "used": 0 },
    "ACCESS": { "total": 0, "used": 0 },
    "PON": { "total": 0, "used": 0, "max_subscribers": 0 },
    "MANAGEMENT": { "total": 1, "used": 1 }
  }
}
```

Counting rules:
- `ACCESS`/`UPLINK`: linked interfaces count
- `PON` on OLT: provisioned ONTs resolved to this OLT (current model aggregates at OLT level, not per-PON-interface)
- `MANAGEMENT`: `1` if mgmt interface exists, else `0`

## 3.3 Link Details Panel

Editable:
- `physical_medium` from `GET /api/optical/fiber-types`
- `length_km` (float, e.g. step `0.01`)

Read-only:
- computed `link_loss_db`

Validation:
- inline field-level errors with backend code mapping

Save strategy:
- explicit save in MVP (debounce optional later)

## 3.4 Passive/OLT/ONT Panels

Passive (ODF/NVT/HOP/Splitter):
- `insertion_loss_db` editable (min 0, step 0.1), debounced patch
- Splitter-specific used/total badge from splitter parameters

OLT:
- `tx_power_dbm` editable (slider + numeric)
- dependent ONT count + last recompute timestamp

ONT Analysis:
- display Tx, total attenuation, Rx, margin, status
- path breakdown table (order, element, id, contribution, cumulative)
- empty state if no path
- if override forces UP while signal path invalid, show warning banner

Note:
- `deviceSignalUpdated` stays compact; full path details are fetched via dedicated API (for example `GET /api/devices/:id/optical-path`).

## 4. Link/Container UX Constraints

Rules:
- Containers (`POP`, `CORE_SITE`) are never valid link endpoints.
- In link mode, clicking a container opens child-device selector filtered by link rules.
- Server must still reject any container endpoint payloads.
- `mgmt0` is not a valid link endpoint.
- Link compatibility is validated against `LINK_TYPE_RULES`.
- Splitter oversubscription is blocked with explicit error codes/details.

## 5. Cockpit Mapping and Rendering Semantics

Stable mapping:
- `CORE_ROUTER`, `EDGE_ROUTER` -> Router cockpit
- `OLT` -> OLT cockpit
- `AON_SWITCH` -> AON switch cockpit
- `ONT`, `BUSINESS_ONT` -> ONT cockpit
- `AON_CPE` -> AON CPE cockpit
- passive inline (`ODF`, `NVT`, `SPLITTER`, `HOP`) -> passive cockpit
- `POP` -> POP cockpit
- `CORE_SITE` -> core-site cockpit

Render invariants:
- containers in background layer,
- children and links above,
- containment/slot attraction may guide child placement but must remain deterministic.

## 6. Capacity, Animation, Congestion

## 6.1 Router Total Capacity Contract

Backend response compatibility:
- `parameters.capacity.effective_device_capacity_mbps`
- `parameters.effective_capacity_mbps`

UI convention:
- label `TotCap (Gbps)`
- value `current / max` with deterministic rounding/unit rules

## 6.2 Link Flow Animation

- Animate only when utilization > 0.
- Speed scales with utilization but is capped.
- Dash spacing scales with physical link length.
- Suspend animation while tab is hidden.

## 6.3 Congestion with Hysteresis

Thresholds:
- device/link enter >= 100%, clear <= 95%
- GPON segment enter >= 95%, clear <= 85%

Semantics:
- sticky warning behavior to avoid flicker
- update indicators only on threshold crossings

## 7. Error Codes and Failure Semantics

Error code source-of-truth:
- centralized backend enum/module only

Representative codes:
- `POOL_EXHAUSTED`
- `P2P_SUPERNET_EXHAUSTED`
- `DUPLICATE_MGMT_INTERFACE`
- `DUPLICATE_LINK`
- `INVALID_PROVISION_PATH`
- `INVALID_LINK_TYPE`
- `OVERRIDE_CONFLICT`
- `ATTENUATION_PARAM_INVALID`
- `FIBER_TYPE_INVALID`
- `SIGNAL_PATH_INCOMPLETE`
- `INVALID_DEBUG_INJECTION`
- `DEBUG_INJECTION_LIMIT`
- `FEATURE_DISABLED`
- `SANDBOX_LOAD_VERSION_MISMATCH`

Rules:
- Each error must map to deterministic HTTP status and machine-readable code.
- UI toasts/panels render code + short actionable detail.

## 8. Determinism and Ordering

Deterministic guarantees:
- Stable sorting for bulk outputs and topology payloads.
- Canonical endpoint ordering where required (for example routed p2p semantics).
- Stable path tie-break with path signature.
- Realtime ordering as defined in section 1.4.

## 9. Deferred Extensions

Deferred but tracked:
- multiple OLT path comparison
- attenuation heatmap overlay
- path recommendation view
- additional viewer tabs (IPAM dashboard, signal monitor)
- lasso selection
- bulk override operations
- sandbox diff view

## 10. Cross-Document Contract

- `04_signal_budget_and_overrides.md`: signal events, classification and override precedence
- `04_links_and_batch.md`: link lifecycle, batch semantics and validation
- `07_container_model_and_ui.md`: container behavior and child handling
- `13_api_reference.md`: canonical REST/Socket contracts
