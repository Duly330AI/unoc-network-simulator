# Recovery Status

This working copy is the **main recovery base** of the UNOC project
(Python/FastAPI + Go engine + Vue 3 `unoc-frontend-v2` line, snapshot of
2026-03, recovered 2026-07-01 and verified in a controlled run audit on
2026-07-02).

Baseline commit: `4c4974c` (branch `master`); the restored GitHub remote
`Duly330AI/unoc-repo` contains the same tree plus follow-up documentation
commits.

## Confirmed working (run audit 2026-07-02)

Verified against a live local stack (Postgres + traffic-engine + backend +
Vite) with read-only API probes, a headless-Chrome UI smoke (0 console errors,
0 failed requests) and targeted tests (12/12 backend tests green for the
features below; Go `internal/optical` and `internal/graph` tests green).

| Feature / subsystem | Status | Evidence |
| --- | --- | --- |
| **IPAM** | ✅ confirmed | `GET /api/ipam/pools` 200; IPAM tab renders pool table (CIDR, allocation, utilization); `test_ipam_endpoint.py`, `test_ipam_edge_cases.py` pass |
| **Interfaces** | ✅ confirmed | `GET /api/devices/{id}/interfaces` 200; DeviceInterfaces section in DetailsPanel; `test_interfaces_mac_and_api.py`, `test_interface_addresses_api.py` pass |
| **Debug Viewer** | ✅ confirmed | `GET /api/debug/full-snapshot` 200 (11 sections); Debug tab renders live snapshot with refresh; gated by `UNOC_DEV_FEATURES=1`; `test_debug_full_snapshot.py` passes |
| **Topology / Canvas** | ✅ confirmed | SVG canvas renders seeded devices, device palette, cockpit overlays, details panel |
| **Go Traffic Engine** | ✅ confirmed | Built from source (Go 1.25), HTTP :8080, live tick loop (~2 ms/tick against seeded topology) |
| Go optical/batch/status gRPC services | ✅ build + optional | Built from source; backend has Python fallback when they are not running |
| PostgreSQL via docker compose | ✅ confirmed | `docker compose up -d postgres`; schema created via `scripts/reset_dev_db.py` |

See [docs/local_start.md](docs/local_start.md) for the exact verified startup
procedure.

## Intentionally out of scope

- **VLAN** — the VLAN implementation of the Aug/Sep 2025 line is not present
  in this snapshot (design docs survive under `docs/guides/network-design/` and
  `docs/archive/2025-09-19-legacy/`). A working VLAN data model exists in the
  separate `unoc-2` repository (`prisma/schema.prisma`, `server/sessionService.ts`)
  and porting it back is planned **future work — deliberately not started yet**.
- No feature additions, refactors, or merges with other recovered lines as part
  of stabilization.

## Known test drift / known issues

1. **2 frontend specs fail by assertion drift** —
   `src/__tests__/DetailsPanel.interfaces.spec.ts` and
   `src/__tests__/DetailsPanel.interfaces.sort.spec.ts` fail with
   `expected +0 to be 2` (component renders 0 mocked rows). This failure exists
   in the committed snapshot itself (work tree clean vs. HEAD) — runtime
   behavior of the Interfaces UI is verified working; the specs' mocking is
   stale, not the feature.
2. **`engine-go/internal/batch/create_test.go` is stale** — does not compile
   (`too many errors`); the batch service binary itself builds fine. Test file
   needs re-sync with the current package API.
3. **`status.proto` gencode major-version warning** — the checked-in
   `status_pb2.py` was generated with protobuf 5.27.x while the runtime is now
   6.31.1 (one major older ⇒ warning only, per protobuf compatibility window).
   Regenerating the stubs with grpcio-tools 1.75.1 would silence it; not done
   during stabilization to avoid touching generated source.
4. **Dependency pins were stale relative to checked-in gencode** — fixed in
   `requirements.txt` (protobuf 5.29.2 → 6.31.1, grpcio/grpcio-tools 1.68.1 →
   1.75.1, matching what the generated `backend/proto/*_pb2*.py` files require).
   `pyinstrument` is commented out (no cp313 wheel; only used by the perf
   harness, which has a cProfile fallback).
5. **Full backend test suite (134 files) not yet run** — only targeted
   feature tests were executed during the audit. Integration (`-m integration`)
   and perf (`-m perf`) markers are excluded by default via `pytest.ini`.
6. **Playwright E2E suite (`tests-e2e/`) not yet run** — several specs are
   mutating (e.g. bulk-create); requires a dedicated, disposable environment.

## Environment notes

- Python 3.13 venv, Node 22 / npm 11, Go 1.25, Docker 28 (verified versions).
- `UNOC_DEV_FEATURES=1` is required for the Debug endpoints/tab.
- `UNOC_DISABLE_RELOAD=1` recommended for background/service-style runs.
- The Go traffic engine on :8080 is **mandatory** for backend startup
  (`backend/services/traffic/v2_runner.py` has no Python fallback).
