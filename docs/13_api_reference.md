# 13. API Reference

This document is the canonical external contract for REST endpoints and Socket events.

Base conventions:
- Base path: `/api`
- Content type: `application/json`
- IDs: UUID-style identifiers unless explicitly stated otherwise
- Error responses include machine-readable `code`

## 1. REST Conventions

Standard response behavior:
- `2xx` for success
- `4xx` for client errors with deterministic error code
- `5xx` for unhandled server errors

Canonical error envelope:

```json
{
  "error": {
    "code": "INVALID_LINK_TYPE",
    "message": "Human-readable summary",
    "details": { "field": "link_type" }
  },
  "request_id": "req_..."
}
```

## 2. Topology APIs

- `GET /api/topology`
  - returns full graph payload for client bootstrap
  - response: `{ nodes: [], edges: [], topo_version: number }`

## 3. Device APIs

- `GET /api/devices`
- `POST /api/devices`
- `GET /api/devices/:id`
- `PATCH /api/devices/:id`
- `DELETE /api/devices/:id`
- `POST /api/devices/:id/provision`
- `PATCH /api/devices/:id/override`

Contract notes:
- creation/provisioning enforces parent/role constraints
- patch operations return deterministic validation errors for unsupported fields

## 4. Link APIs

- `GET /api/links`
- `POST /api/links`
- `DELETE /api/links/:id`
- `POST /api/links/batch/create`
- `POST /api/links/batch/delete`
- `PATCH /api/links/:id`
- `PATCH /api/links/:id/override`

Contract notes:
- container endpoint IDs are rejected
- compatibility/link-rule validations return canonical error codes
- batch responses include partial-failure details when applicable
- in ODF-as-aggregator mode, direct `OLT <-> ONT` link creation is rejected

## 5. Ports and Interfaces APIs

- `GET /api/ports/summary/:device_id`
- `GET /api/ports/summary?ids=...`
- `GET /api/ports/ont-list/:device_id`
- `GET /api/interfaces/:deviceId`

Contract notes:
- ports summary response is aggregate-by-role (`device_id`, `total`, `by_role`)
- role semantics include `MANAGEMENT.used = 1|0` depending on mgmt interface presence
- current PON `used` is OLT-level aggregated ONT count in the active model
- interfaces response includes addresses where present

## 6. Optical and Catalog APIs

- `GET /api/optical/fiber-types`
- `GET /api/catalog/hardware?type=...`
- `GET /api/catalog/hardware/:catalog_id`
- `GET /api/devices/:id/optical-path` (details endpoint for full path breakdown)

Contract notes:
- UI uses fiber-types endpoint as source-of-truth
- compact signal events may omit path details; fetch via details endpoint

## 7. Metrics and Simulation APIs

- `GET /api/metrics/snapshot`
- `GET /api/sim/status`

Contract notes:
- snapshot used after reconnect/version gaps
- status endpoint exposes engine runtime health

## 8. Socket Event Contract

Transport:
- Socket.io under API namespace/path configured by server deployment

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

Gap handling:
- clients detect non-monotonic/gapped `topo_version`
- on gap, clients resync topology + metrics snapshots

## 9. Server->Client Event Inventory

Core events:
- `deviceCreated`
- `deviceStatusUpdated`
- `deviceSignalUpdated`
- `deviceOverrideChanged`
- `deviceContainerChanged`
- `linkAdded`
- `linkUpdated`
- `linkDeleted`
- `linkStatusUpdated`
- `deviceMetricsUpdated`
- `linkMetricsUpdated` (when enabled)
- `segment.congestion.detected`
- `segment.congestion.cleared`

Ordering contract (within one window):
1. topology/optical mutation updates
2. signal updates
3. status updates
4. metrics/congestion updates

## 10. Error Code Reference (Canonical)

Representative codes:
- `INVALID_PROVISION_PATH`
- `ALREADY_PROVISIONED`
- `POOL_EXHAUSTED`
- `P2P_SUPERNET_EXHAUSTED`
- `DUPLICATE_MGMT_INTERFACE`
- `DUPLICATE_LINK`
- `INVALID_LINK_TYPE`
- `OVERRIDE_CONFLICT`
- `ATTENUATION_PARAM_INVALID`
- `FIBER_TYPE_INVALID`
- `SIGNAL_PATH_INCOMPLETE`
- `FEATURE_DISABLED`

Every public error path must map to one canonical code and deterministic HTTP status.

## 11. Versioning and Compatibility

Rules:
- breaking contract changes require explicit versioning strategy
- docs and contract tests update in same change
- compatibility aliases (`/api/v1`) must be documented if present

## 12. Contract Testing Requirements

Must be validated by automated tests:
- endpoint existence and method correctness
- payload shape and error envelope
- websocket event names/payloads/order
- gap/reconnect recovery behavior

## 13. Cross-Document Contract

- `05_realtime_and_ui_model.md`: realtime consumption model
- `08_ports.md`: ports semantics
- `10_interfaces_and_addresses.md`: interface/address model
- `11_traffic_engine_and_congestion.md`: metrics and congestion behaviors
- `12_testing_and_performance_harness.md`: contract test strategy
