# 09. Cockpit Nodes (Components, Props, Rendering Rules)

This document defines cockpit mapping, prop contracts, rendering invariants, and performance/a11y requirements.

Stack context:
- Frontend: React + TypeScript + React Flow
- Data sources: REST summaries + socket deltas + shared stores

## 1. Device-Type to Component Mapping

Canonical mapping:
- `CORE_ROUTER` -> `RouterCockpit`
- `EDGE_ROUTER` -> `RouterCockpit`
- `OLT` -> `OLTCockpit`
- `AON_SWITCH` -> `AONSwitchCockpit`
- `ONT`, `BUSINESS_ONT` -> `ONTCockpit`
- `AON_CPE` -> `AONCPECockpit`
- `POP` -> `POPCockpit`
- `CORE_SITE` -> `CoreSiteCockpit`
- passive inline (`ODF`, `NVT`, `SPLITTER`, `HOP`) -> `PassiveCockpit`

Fallback:
- unknown type -> `GenericCockpit`

## 2. Common Props Contract

Normalized props:
- `device`: canonical device DTO
- `metrics?`: current metrics slice
- `portSummary?`: aggregated summary from `GET /api/ports/summary/:device_id`
- `links?`: neighboring link metadata
- `selectionState?`: optional UI selection metadata

Capacity compatibility fields:
- `parameters.capacity.effective_device_capacity_mbps`
- `parameters.effective_capacity_mbps`

Resilience:
- optional props must soft-fail to neutral state

## 3. Rendering Rules by Cockpit

## 3.1 RouterCockpit

- label exactly `TotCap (Gbps)`
- value format: `current / max` with deterministic rounding
- data source: metrics + capacity fields
- does not require `portSummary` by default

## 3.2 OLTCockpit

- uses `portSummary.by_role.PON` for occupancy/capacity badges
- per-interface matrix detail (if shown) comes from interface-specific data source, not summary endpoint
- drill-down ONT lists via `/api/ports/ont-list/:device_id`

## 3.3 AONSwitchCockpit

- uses `portSummary.by_role.ACCESS` and `UPLINK` for used/total badges

## 3.4 ONTCockpit and AONCPECockpit

- compact KPI view
- ONT shows optical summary fields where available (`received`, `margin`, `signal_status`)
- AON CPE omits optical-only rows

## 3.5 PassiveCockpit

- status summary and role-specific badges
- splitter `used/total` sourced from splitter parameter contract

## 3.6 Container Cockpits

- aggregate child health with precedence `DOWN > DEGRADED > UP`
- aggregate occupancy/traffic as read model only
- never treated as link endpoints

## 4. Realtime Integration

Cockpits subscribe to shared stores updated by:
- metrics/status/link deltas
- snapshot replacement flows after reconnect/gap

Gap behavior:
- on `topo_version` gap, clients resync before applying subsequent deltas

## 5. Accessibility

- ARIA labels for KPIs and matrices
- keyboard navigation with visible focus
- high-contrast support
- status not conveyed by color alone

## 6. Performance

- stable props + memoization to reduce rerenders
- suspend expensive polling for offscreen/inactive nodes
- batch visual updates under burst deltas
- virtualization for large matrices is deferred

## 7. Testing Baseline

- mapping coverage (`device_type -> cockpit`)
- TotCap formatting and capacity fallback tests
- role-summary badge rendering tests
- optional-prop resilience tests
- reconnect/snapshot reconciliation tests

## 8. Error and Fallback Behavior

- missing metrics -> placeholders
- malformed optional payload -> ignore + diagnostic log
- unknown device type -> `GenericCockpit`

## 9. Cross-Document Contract

- `05_realtime_and_ui_model.md`
- `07_container_model_and_ui.md`
- `08_ports.md`
- `11_traffic_engine_and_congestion.md`
- `13_api_reference.md`
