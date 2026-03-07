# 04. Links and Batch Operations

This document defines the authoritative contract for link modeling, link lifecycle operations, batch processing, effective status behavior, and link-related realtime events.

Stack context:
- Backend: Node.js + Express + Prisma + Socket.io
- Frontend: React + TypeScript + React Flow
- Optional accelerator track: external batch/status service with safe fallback

## 1. Link Model

Links connect two interfaces and represent physical or logical connectivity.

Core fields:
- `id`: unique link id
- `a_interface_id`: endpoint A interface
- `b_interface_id`: endpoint B interface
- `length_km`: physical length in km
- `status`: stored logical status (`UP`, `DOWN`, `DEGRADED`, `BLOCKING` where applicable)
- `effective_status`: computed status including endpoint/admin influence
- `admin_override_status`: explicit admin override
- `link_type`: medium/type category (`ETHERNET`, `FIBER`, `WIRELESS`)
- `metadata`: JSON payload (fiber type, cable id, notes, custom tags)

## 2. Link Rules (Validation)

Mandatory constraints:
1. No self-link at device level (both interfaces cannot belong to same device unless explicitly allowed diagnostic mode).
2. Interface uniqueness (one interface in max one active link unless logical-multi mode exists).
3. Interface role compatibility (for example UNI<->NNI policy table).
4. Device type compatibility with provisioning/path rules (for example OLT<->passive chain<->ONT).
5. Container endpoints (`POP`, `CORE_SITE`) are invalid as link endpoints.

## 3. Link CRUD Contract

## 3.1 Create Link

```http
POST /api/links
Content-Type: application/json

{
  "a_interface_id": 1,
  "b_interface_id": 2,
  "length_km": 5.0,
  "status": "UP",
  "link_type": "FIBER",
  "metadata": {"fiber_type": "SM", "cable_id": "CAB-001"}
}
```

Success response:
```json
{
  "id": 123,
  "a_interface_id": 1,
  "b_interface_id": 2,
  "length_km": 5.0,
  "status": "UP",
  "effective_status": "UP",
  "link_type": "FIBER",
  "metadata": {"fiber_type": "SM", "cable_id": "CAB-001"},
  "created_at": "2026-03-07T10:00:00Z"
}
```

## 3.2 Update Link

```http
PATCH /api/links/{link_id}
Content-Type: application/json

{
  "length_km": 7.5,
  "metadata": {"fiber_type": "SM", "notes": "Replaced cable"}
}
```

## 3.3 Delete Link

```http
DELETE /api/links/{link_id}
```

Preferred behavior:
- asynchronous acceptance for heavy recompute paths.
- response shape:

```json
{
  "accepted": true,
  "job_id": "job_abc123"
}
```

If synchronous mode is enabled for small topologies, return deterministic success payload and still emit deletion event.

## 3.4 Set Admin Override

```http
PATCH /api/links/{link_id}/override
Content-Type: application/json

{
  "admin_override_status": "DOWN"
}
```

Admin override changes may be processed async to avoid blocking on propagation.

## 4. Effective Link Status

Effective status inputs:
1. Admin override (highest precedence)
2. Endpoint effective statuses
3. Link stored status
4. Optical/path health for optical-relevant links

Precedence order:
1. Admin override if set
2. `DOWN` if either endpoint is `DOWN`
3. `DEGRADED` if either endpoint is `DEGRADED`
4. `UP` if endpoints are viable and optical/logical checks pass

`is_link_passable` remains the shared traversal gate for status, dependency, and traffic engines.

## 5. Batch Operations

Motivation:
- Large topology creation is too slow with sequential single-link requests.
- Batch endpoints allow high-throughput validation and commit workflows.

## 5.1 Batch Create

```http
POST /api/links/batch
Content-Type: application/json

{
  "links": [
    {
      "a_interface_id": 1,
      "b_interface_id": 2,
      "length_km": 5.0,
      "status": "UP",
      "metadata": {"fiber_type": "SM"}
    },
    {
      "a_interface_id": 3,
      "b_interface_id": 4,
      "length_km": 3.0,
      "status": "UP",
      "metadata": {"fiber_type": "SM"}
    }
  ],
  "dry_run": false,
  "skip_optical_recompute": false,
  "request_id": "batch-001"
}
```

Response shape:

```json
{
  "created_link_ids": [101, 102],
  "failed_links": [
    {
      "index": 2,
      "a_interface_id": 7,
      "b_interface_id": 8,
      "error_code": "INTERFACE_NOT_FOUND",
      "error_message": "Interface 7 does not exist"
    }
  ],
  "total_requested": 3,
  "total_created": 2,
  "duration_ms": 420,
  "request_id": "batch-001",
  "backend": "native"
}
```

Request options:
- `dry_run`: validate only, no writes
- `skip_optical_recompute`: defer optical recompute
- `request_id`: correlation id

## 5.2 Batch Delete

```http
POST /api/links/batch/delete
Content-Type: application/json

{
  "link_ids": [101, 102, 103],
  "skip_optical_recompute": false,
  "request_id": "batch-delete-001"
}
```

Response includes:
- `deleted_link_ids`
- `failed_links` with `LINK_NOT_FOUND` etc.
- `total_requested`, `total_deleted`, `duration_ms`, `request_id`, `backend`

## 5.3 Batch Health Endpoint

```http
GET /api/batch/health
```

Expected payload:
```json
{
  "status": "ok",
  "backend": "native",
  "available": true,
  "version": "1.0.0"
}
```

## 5.4 Dry-Run Mode

Batch create with `dry_run=true` returns success/failure prediction without any DB mutation.

## 6. Error Codes

Common batch/link error codes:
- `INTERFACE_NOT_FOUND`
- `INTERFACE_ALREADY_LINKED`
- `INTERFACE_SAME_DEVICE`
- `DEVICE_NOT_FOUND`
- `LINK_NOT_FOUND`
- `TRANSACTION_FAILED`
- `VALIDATION_ERROR`
- `FALLBACK_NOT_IMPLEMENTED` (only if fallback path intentionally stubbed)

## 7. Performance and Execution Backends

Primary path:
- native Node.js service with transactional batch logic.

Optional accelerator path:
- external high-performance batch service (for example Go) via gRPC/HTTP with fallback.
- API response field `backend` must indicate execution source (`native`, `accelerator`, or `fallback`).

Safety requirements:
- identical functional contract across backends,
- deterministic error model,
- fallback without service outage.

## 8. Realtime Events

Link operations emit websocket events:
- `link.created`
- `link.deleted`
- `link.updated`
- `link.status_changed`
- `batch.completed`

Example:
```json
{
  "type": "link.created",
  "data": {
    "link_id": 123,
    "a_interface_id": 1,
    "b_interface_id": 2,
    "effective_status": "UP"
  },
  "correlation_id": "batch-001",
  "timestamp": "2026-03-07T10:00:00Z"
}
```

## 9. Testing Baseline

Minimum tests:
- CRUD validation tests (self-link, duplicates, role mismatch, container endpoint rejection).
- Batch create/delete tests with partial failures.
- Dry-run no-write guarantee tests.
- Concurrency tests (conflicting batch requests).
- Event emission tests (single and batch operations).
- Optional accelerator parity tests (`native` vs `accelerator` behavior).

## 10. Observability

Structured logs:
- `link.create.start/success/failure`
- `link.batch.create.start/complete/failure`
- `link.batch.delete.start/complete/failure`

Metrics:
- `link_create_duration_ms`
- `link_batch_create_duration_ms`
- `link_batch_delete_duration_ms`
- `link_batch_failed_total{error_code}`
- `link_batch_backend_total{backend}`

## 11. Backward Compatibility Note

Some legacy environments use `/api/v1/...` routes.
Current canonical contract in this repository is `/api/...`.
If compatibility aliases are exposed, they must preserve identical request/response semantics.
