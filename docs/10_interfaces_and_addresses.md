# 10. Interfaces and Addresses

This document defines the interface/address data model, deterministic MAC and naming rules, and API contracts.

Stack context:
- Backend: Node.js + Express + Prisma
- Frontend: React + TypeScript

## 1. Data Model

## 1.1 Interface Entity

An interface represents a physical or logical device port.

Core fields:
- `id` (UUID)
- `device_id` (FK -> Device)
- `name` (deterministic system name, for example `mgmt0`, `pon1`, `uplink0`)
- `mac_address` (globally unique within dataset)
- `role` (`PON | UPLINK | ACCESS | TRUNK | MGMT`)
- `status` (`UP | DOWN | DEGRADED | BLOCKING` where supported by runtime contract)
- `profile_name` (optional profile binding)
- `capacity` (nullable numeric capacity contract for non-PON and profile-derived ports)

Constraints:
- unique `(device_id, name)`
- unique `mac_address`
- role value must be canonical enum

## 1.2 Address Entity

An address represents an IP assignment to one interface.

Core fields:
- `id` (UUID)
- `interface_id` (FK -> Interface)
- `ip` (IPv4 dotted string in MVP)
- `prefix_len` (CIDR prefix)
- `is_primary` (boolean)
- `vrf` (optional logical routing context)

Constraints:
- at most one primary address per interface+VRF
- uniqueness rules follow IPAM policy (global or VRF-scoped by configuration)

## 2. Deterministic MAC Allocation

MAC assignment is centralized.

Policy:
- locally administered OUI prefix
- deterministic monotonic allocator behavior
- collision-safe under concurrency

Allocator requirements:
- one allocation path (`MacAllocator` service)
- atomic reservation/commit semantics
- retry strategy on uniqueness conflict

Determinism expectation:
- with clean DB + same provisioning order, generated MAC sequence is reproducible.

## 3. Deterministic Interface Naming

Naming is derived from hardware model/profile and role.

Rules:
- pattern `{base}{index}`
- management defaults to `mgmt0`
- stable ordering by profile definition and canonical role priority

Examples:
- `pon1`, `pon2`
- `uplink0`
- `access5`

Invariants:
- no name gaps/reordering for identical model inputs unless profile changed
- renames require explicit migration strategy

## 4. Provisioning and IPAM Integration

Provisioning responsibilities:
- create required interface set for device type/model
- assign deterministic names and MACs
- assign management/service addresses by IPAM policy
- ensure idempotency on repeated provisioning attempts

Integration rules:
- management interface creation must respect duplicate guards
- `/31` point-to-point allocations follow routed-link policy where applicable
- address uniqueness and pool exhaustion map to canonical error codes

## 5. API Contracts

## 5.1 `GET /api/interfaces/:deviceId`

Purpose:
- return interfaces for one device including assigned addresses

Normative interface item shape:

```json
{
  "id": "...",
  "name": "mgmt0",
  "mac": "02:55:4E:00:00:01",
  "role": "MGMT",
  "status": "UP",
  "capacity": null,
  "addresses": [
    {
      "ip": "10.0.0.1",
      "prefix_len": 24,
      "is_primary": true,
      "vrf": "default"
    }
  ]
}
```

Contract notes:
- deterministic ordering by role+name
- empty address list allowed
- unknown `deviceId` returns `404`

## 5.2 Optional Follow-up Endpoints (track)

Potential extensions:
- `GET /api/interfaces/:deviceId/:interfaceId`
- interface address patch/add/remove endpoints

If added, versioned contract tests are mandatory.

## 6. Error Semantics

Representative errors:
- `DUPLICATE_MGMT_INTERFACE`
- `POOL_EXHAUSTED`
- `P2P_SUPERNET_EXHAUSTED`
- uniqueness/conflict errors for MAC/name/address constraints

Rules:
- deterministic 4xx mapping with machine-readable code
- contextual detail suffix for operator debugging

## 7. Testing Baseline

Backend tests:
- deterministic name generation per model/profile
- deterministic MAC allocation and no-collision under concurrent provisioning
- primary-address uniqueness rules
- API ordering and shape validation for `GET /api/interfaces/:deviceId`

Integration tests:
- provisioning creates expected interfaces/addresses for each device type
- repeat provisioning idempotency

## 8. Observability

Logs:
- interface creation summary per provisioning action
- MAC allocator conflicts/retries
- address assignment failures with pool context

Metrics:
- `interfaces_created_total{role}`
- `mac_allocator_conflicts_total`
- `ip_assign_failures_total{reason}`

## 9. Future Extensions

- IPv6 address model and dual-stack assignment
- explicit interface mutation APIs with audit trail
- VRF-aware multi-tenant uniqueness policies

## 10. Cross-Document Contract

- `02_provisioning_model.md`: creation/dependency logic
- `03_ipam_and_status.md`: pool allocation and status semantics
- `08_ports.md`: summary and occupancy views
- `13_api_reference.md`: canonical API/error shapes
