# 04. Signal Budget and Overrides

This document defines the authoritative signal/optical model, effective status propagation behavior, deterministic path selection, and admin override semantics.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow

## 1. Status Simulation and Propagation

## 1.1 Single Source of Truth

Final computed status is produced only by the centralized status service.

Core rules (without admin override):
- Always-online classes -> `UP` baseline.
- Passive devices:
  - display/propagation state based on upstream/downstream viability snapshots,
  - passive UP/DEGRADED flags do not directly alter optical path math.
- Active devices:
  - unprovisioned -> `DOWN`,
  - provisioned -> dependency-gated (`UP`/`DEGRADED`/`DOWN` by policy),
  - ONT/Business ONT with `signal_status=NO_SIGNAL` -> `DOWN`.

Admin override precedence:
- `DOWN` override wins over computed values.
- `UP` override can force effective status for diagnostics.
- conflict scenarios are logged (do not silently suppress inconsistencies).

## 1.2 Evaluation Pseudocode

```ts
function computeDeviceStatus(device: DeviceContext): EffectiveStatus {
  if (device.adminOverride === "DOWN") return "DOWN";
  if (device.isAlwaysOnline) return "UP";

  if (device.isPassive) {
    return device.propagationSnapshotReachable ? "UP" : "DEGRADED";
  }

  if (!device.provisioned) return "DOWN";

  if (device.isOntLike && device.signalStatus === "NO_SIGNAL") {
    return "DOWN";
  }

  return device.dependenciesOk ? "UP" : "DEGRADED";
}
```

## 1.3 ONT Effective Online Rule

ONT is effectively online only if:
1. `provisioned=true`
2. optical path resolves to an OLT
3. `signal_status != NO_SIGNAL`
4. no overriding `DOWN` admin state

## 1.4 Edge Cases

- Graph cycles should be blocked at link validation; propagation additionally uses visited guards.
- Orphan passives remain non-UP.
- Bulk mutations may be coalesced into one recompute window.

## 2. Signal Budget Model

## 2.1 Path Resolution

Goal:
- For each ONT, resolve exactly one upstream OLT path through optical topology.
- If multiple candidates exist, choose the minimum attenuation path with deterministic tie-breakers.

Algorithm:
1. Run Dijkstra on optical graph.
2. Link weight: `length_km * attenuation_db_per_km` (resolved via physical medium).
3. Add insertion losses for interior passive nodes.
4. Sort reached OLT candidates by:
   - `total_attenuation_db`
   - `total_physical_length_km`
   - `hop_count`
   - `olt_id`
   - `path_signature`
5. Pick first candidate.

Determinism note:
- `path_signature` tie-break guarantees stable selection across recomputes and avoids path flapping.

## 2.2 Attenuation Components

For chosen path `P`:
- link loss: `sum(length_km * attenuation_per_km)`
- passive insertion loss: `sum(insertion_loss_db)` for interior passives
- splitter loss is represented through insertion loss field
- connector loss is deferred in this phase

Formula:

```text
total_path_attenuation_db = sum(link_loss_db) + sum(passive_insertion_loss_db)
```

## 2.3 Receive Power and Margin

```text
received_power_dbm = olt.tx_power_dbm - total_path_attenuation_db
margin_db = received_power_dbm - ont.sensitivity_min_dbm
```

If no path resolves -> `signal_status = NO_SIGNAL`.

## 2.4 Classification Thresholds

| Signal Status | Condition |
| --- | --- |
| OK | `margin_db >= 6.0` |
| WARNING | `3.0 <= margin_db < 6.0` |
| CRITICAL | `0 <= margin_db < 3.0` |
| NO_SIGNAL | `margin_db < 0` or unresolved path |

## 2.5 Emission Rules

Emit `deviceSignalUpdated` if any condition matches:
- signal class/status changed
- absolute received power delta >= `0.1 dB`
- margin boundary crossed

If ONT effective status changes because of signal transition:
- emit `deviceStatusUpdated` after signal event in same coalesced window.

## 2.6 Recompute Triggers

- Link create/delete on candidate paths
- Link `length_km` or `physical_medium_id` updates
- Physical medium attenuation changes (global invalidation)
- Passive insertion loss changes
- OLT `tx_power_dbm` updates
- ONT `sensitivity_min_dbm` updates
- ONT provisioning events

## 2.7 Cache Invalidation Scope (MVP)

Current strategy:
- global invalidation for topology/optical-affecting mutations
- path graph cache and optical resolver cache cleared together
- recompute currently all provisioned ONTs for correctness-first behavior

Selective affected-set recompute can be added in later phase.

## 2.8 Signal Payload Shape

Target event payload:

```json
{
  "id": "<ont-id>",
  "received_dbm": -17.5,
  "signal_status": "OK",
  "margin_db": 12.5,
  "path": {
    "olt_id": "<olt-id>",
    "total_attenuation_db": 22.5,
    "segments": [
      { "src": "<nodeA>", "dst": "<nodeB>", "link_id": "<L1>", "attenuation_db": 5.2 },
      { "src": "<nodeB>", "dst": "<nodeC>", "link_id": null, "attenuation_db": 3.5 }
    ]
  }
}
```

Compact mode is allowed for high-frequency streams:
- `{id, received_dbm, signal_status, margin_db}`

If compact mode is used, full path/segment details must be available via dedicated API.

## 2.9 Validation and Errors

- negative `length_km` -> `ATTENUATION_PARAM_INVALID`
- unknown fiber type key -> `FIBER_TYPE_INVALID`
- negative insertion loss -> `ATTENUATION_PARAM_INVALID`

## 2.10 Fiber Types Catalog

Fiber types are versioned constants and API-exposed source-of-truth.

Reference keys:
- `SMF_G652D` (0.35)
- `SMF_G657A1` (0.35)
- `SMF_G657A2` (0.35)
- `MMF_OM3` (3.50)
- `MMF_OM4` (3.00)

API:
- `GET /api/optical/fiber-types`

UI must derive dropdown/options from API, not hardcoded local lists.

## 3. Admin Override System

Field:
- `admin_override_status` on devices and links (`null | UP | DOWN | BLOCKING` by policy)

Evaluation order:
1. compute base status
2. apply link overrides (path viability impact)
3. apply device overrides

Conflict handling:
- If override forces `UP` while mandatory path/signal constraints are missing, keep forced status but emit `OVERRIDE_CONFLICT` diagnostic event.

## 4. Event Ordering Contract

Within one recompute window:
1. link/optical derived changes
2. `deviceSignalUpdated`
3. `deviceStatusUpdated`

Override mutation events are immediate and carry correlation metadata.

## 5. Testing Baseline

Minimum tests:
- deterministic path selection under equal-cost candidates
- threshold boundary transitions (OK/WARNING/CRITICAL/NO_SIGNAL)
- emission gating (`>=0.1 dB` and class boundary)
- global cache invalidation correctness
- override precedence and conflict diagnostics
- event ordering assertions

## 6. Observability

Logs:
- `optical.recompute.start/complete/failure`
- `signal.classification.changed`
- `status.override.conflict`

Metrics:
- `optical_recompute_duration_ms`
- `optical_recompute_onts_total`
- `signal_status_changes_total{status}`
- `override_conflicts_total`

## 7. Cross-Document Contract

- `03_ipam_and_status.md`: effective status and passability base semantics
- `04_links_and_batch.md`: link lifecycle and override mutation flows
- `05_realtime_and_ui_model.md`: websocket envelope and client handling
- `13_api_reference.md`: public endpoint/event surface
