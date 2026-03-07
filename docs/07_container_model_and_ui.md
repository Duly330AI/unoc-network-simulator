# 07. Container Model and UI (POP, CORE_SITE)

This document defines container semantics, backend validation rules, and UI behavior for `POP` and `CORE_SITE`.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow

## 1. Scope and Intent

Containers are organizational topology entities.

Supported container types:
- `POP`
- `CORE_SITE`

Container design goals:
- visually group infrastructure
- provide aggregate cockpit views (occupancy/health/traffic summary)
- preserve strict network semantics by keeping links/status/pathfinding on real endpoints

Non-goals:
- containers are not routing/switching entities
- containers are not optical path elements
- containers are not link endpoints

## 2. Authoritative Parent/Child Rules

Backend rules are authoritative and must be enforced on every create/update/provisioning path.

Rules:
- `POP` and `CORE_SITE`:
  - cannot have parent containers (`parent_container_id = null`)
  - may host eligible child devices
- `OLT` and `AON_SWITCH`:
  - parent optional
  - if parent is set, parent must be `POP` (policy baseline)
- ONT-family and `AON_CPE`:
  - cannot act as parent
- Cycle prevention:
  - no self-parenting
  - no indirect loops

Validation outcome:
- invalid assignments return deterministic validation errors
- UI hints (slots/drop targets) never bypass backend validation

## 3. Container UI and Canvas Behavior

## 3.1 Cockpit and Layout Behavior

Container cockpits provide:
- occupancy (`children_used / capacity` when capacity policy exists)
- aggregate health (`DOWN > DEGRADED > UP` precedence)
- summary traffic indicators for quick scanning

Rendering invariants:
- container frame layer below devices/links
- child devices remain normal graph entities
- no container-imposed mutation of child business state

## 3.2 Drag-and-Drop Assignment

Interaction:
- dragging a device into/out of a container patches `parent_container_id`
- unassign is represented by `parent_container_id = null`

UX rules:
- valid targets are highlighted
- invalid targets pre-rejected visually
- failed backend validation reverts optimistic UI state

## 3.3 Slot Anchors and Containment

Container slots are UI guidance, not semantic topology ports.

Rules:
- near-anchor snapping for compatible device classes
- gentle containment keeps child nodes inside bounds
- pinned nodes remain pinned; edge clamp only when needed
- deterministic placement policy to reduce visual jitter

## 4. Link Creation with Container Proxy

Containers are never link endpoints.

Link-mode behavior:
1. user targets container
2. UI opens child-selector modal
3. modal lists only valid children for the current link context
4. selected child becomes real endpoint

If no valid target exists:
- show toast (`No valid targets in container`)
- reset/exit link action safely

Backend hard-block:
- any direct container endpoint payload must be rejected, even if UI proxy exists

## 5. Realtime and Event Contract

Container reassignment event:

```json
{
  "id": "dev_123",
  "parent_container_id": "container_456"
}
```

Unassign event:

```json
{
  "id": "dev_123",
  "parent_container_id": null
}
```

Event rules:
- use canonical `deviceContainerChanged`
- ordering follows global realtime contract (mutation -> derived updates)
- link-proxy emits normal link events only; no special proxy event type required

## 6. Metrics and Health Aggregation

Container aggregation is a read model for cockpit UX.

Health precedence:
- if any child `DOWN` -> container `DOWN`
- else if any child `DEGRADED` -> container `DEGRADED`
- else -> `UP`

Traffic summary:
- derived from child metric stream/store
- does not replace per-device source-of-truth metrics

Occupancy:
- rendered from child counts and optional policy capacity
- splitter-specific port usage stays on splitter contract, not container contract

## 7. Pathfinding, Status, Optical Interaction

Containers are excluded from logical/optical graph computations.

Implications:
- pathfinding uses real devices and links only
- effective status and passability are computed per device/link independent of container membership
- optical recompute operates on ONT<->OLT paths independent of container nesting

Topology mutation impact:
- parent reassignment can trigger graph/version invalidation where required
- container-only visual changes must not alter link/path semantics

## 8. Palette, Seeding, and Defaults

Requirements:
- `POP` and `CORE_SITE` are creatable from palette
- defaults include stable visual style and slot presets
- seeded environments include container examples for demos/tests where required

## 9. Error Modes and Constraints

Representative constraints:
- container as link endpoint -> validation error
- invalid parent type -> validation error
- stale IDs in parent/link operations -> `404` contract
- container-in-container or parent loops -> rejected

Invariants:
- containers have no parent
- containers are never link endpoints
- backend rules are source-of-truth

## 10. Splitter V1 Interplay

Splitter rules remain device-level and are not replaced by container logic.

Rules:
- max one ONT per splitter OUT port
- total ONTs cannot exceed OUT capacity

UI:
- splitter cockpit/details display `used/total` from splitter parameters
- container cockpit may include aggregated counts but must not override splitter truth

## 11. API and Data Contract Summary

Entity field:
- `parent_container_id` (nullable)

Events:
- `deviceContainerChanged` (`id`, `parent_container_id`)
- standard link events for proxied link creation

No container-specific link endpoint API:
- proxying is a UI workflow that resolves to real device endpoint IDs

## 12. Deferred Container Tracks

Deferred:
- per-container capacity planning with hard admission policies
- advanced physics stabilization for very large groups
- container-aware scenario templates and batch tooling

## 13. Cross-Document Contract

- `02_provisioning_model.md`: authoritative parent/child and provisioning constraints
- `04_links_and_batch.md`: endpoint/link validation behavior
- `05_realtime_and_ui_model.md`: realtime envelope and interaction contract
- `11_traffic_engine_and_congestion.md`: metric aggregation and congestion semantics
- `13_api_reference.md`: endpoint/event canonical reference
