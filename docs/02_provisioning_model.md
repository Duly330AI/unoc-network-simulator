# 02. Provisioning Model and Provision Matrix

Provisioning transitions a device from `created -> provisioned` and executes an atomic backend workflow.

## 1. Provisioning Transaction (Authoritative Flow)

On `POST /api/devices/:id/provision`, the backend performs:
1. Pre-validation (dependencies, container context, uniqueness).
2. Interface realization (management interface now; p2p uplinks later on link creation).
3. Lazy IP assignment (pool materialization on first use).
4. Phase-1 status recompute for the target device.
5. Optical recompute trigger if optical path can be affected.
6. Delta event emission (`device.status.changed`, `device.optical.updated` when applicable).

Important runtime behavior:
- DB mutations are transactional.
- Status/optical recompute can run async after commit for latency control.

## 2. Provision Matrix (Authoritative)

| Device Type | Provision Allowed? | Required Existing Upstream | Required Container | Disallowed Conditions | Side Effects | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Backbone Gateway | implicit seed | none | none | >1 in single-backbone mode | always-online root | bootstrap-managed in MVP |
| Core Router | yes | Backbone Gateway present | none | missing backbone | mgmt interface + `core_mgmt` IP | multi-core later |
| Router (Edge) | yes | Core Router reachable (logical) | none | no provisioned core router | mgmt interface + `core_mgmt` IP | p2p `/31` later |
| OLT | yes | Core Router logical upstream | POP only (if parent set) | non-POP parent, missing core | mgmt interface + `access_mgmt` IP | parent optional at create time; if set must be POP |
| AON Switch | yes | Core Router logical upstream | POP only (if parent set) | non-POP parent, missing core | mgmt interface + `access_mgmt` IP | parent optional at create time; if set must be POP |
| ONT | yes | OLT reachable via passive chain | none | no OLT path | mgmt interface + `ont_mgmt` IP | signal gating applies |
| Business ONT | yes | OLT reachable | none | no OLT path | mgmt interface + `ont_mgmt` IP | same optical semantics |
| AON CPE | yes | AON Switch reachable (strict) | none | no strict upstream path | mgmt interface + `cpe_mgmt` IP | strict reachability via AON path |
| POP | no | n/a | n/a | provisioning attempted | none | container only |
| Passive Inline (ODF/NVT/Splitter/HOP) | no | n/a | n/a | provisioning attempted | none | passive only |

## 3. Validation Order

1. Existence/type checks (device exists, type provisionable, not already provisioned).
2. Dependency/path validation:
   - logical reachability for router/access classes.
   - optical path validation for ONT/Business ONT.
   - strict AON reachability for AON CPE.
3. Container rules:
   - OLT/AON Switch: parent optional; if set, must be POP.
   - Core/Edge Router: must not have parent container.
   - ONT/Business ONT/AON CPE: parent optional; if set must not be POP/CORE_SITE.
   - Passive inline: parent optional; if set parent must exist.
4. IPAM pool availability (`POOL_EXHAUSTED` on failure).
5. Interface uniqueness (no duplicate management interface).
6. Concurrency guard (re-check provisioned state before commit/final write).

## 4. Provision Algorithm (TypeScript Pseudocode)

```ts
async function provisionDevice(deviceId: string) {
  await prisma.$transaction(async (tx) => {
    const device = await tx.device.findUniqueOrThrow({ where: { id: deviceId } });

    assertProvisionable(device);
    assertNotProvisioned(device);
    await validateDependencies(tx, device);
    await validateContainerRules(tx, device);

    const poolKey = mapDeviceToPool(device.type);
    await ensureIpPool(tx, poolKey);
    const ip = await allocateNextIp(tx, poolKey, device.id);

    await createManagementInterface(tx, device.id, ip);

    await tx.device.update({
      where: { id: device.id },
      data: { provisioned: true },
    });
  });

  // async post-commit hooks
  await recomputeStatusPhase1(deviceId);
  await triggerOpticalRecomputeIfNeeded(deviceId, "provision");
  emitProvisionDeltas(deviceId);
}
```

## 5. Dependency Validation Matrix (Detailed)

| Target Type | Required Checks |
| --- | --- |
| Core Router | at least one Backbone Gateway exists |
| Router (Edge) | at least one Core Router exists (strict) |
| OLT | at least one Core Router exists; parent must be POP if parent present |
| AON Switch | at least one Core Router exists; parent must be POP if parent present |
| ONT/Business ONT | strict path to at least one OLT |
| AON CPE | strict path to Core via AON switch path |

## 6. Error Code Mapping

| Condition | Error Code | HTTP |
| --- | --- | --- |
| Missing dependency/path | `INVALID_PROVISION_PATH` | 400 |
| Already provisioned | `ALREADY_PROVISIONED` | 409 |
| IP pool exhausted | `POOL_EXHAUSTED` | 409 |
| Duplicate management interface | `DUPLICATE_MGMT_INTERFACE` | 400 |
| Required/valid container missing | `CONTAINER_REQUIRED` | 422 |
| Invalid parent for this type | `INVALID_PROVISION_PATH` | 400 |

## 7. Extensibility Hooks

- Pluggable matrix/rules source (constants now, config-driven later).
- Dry-run mode: `POST /api/devices/:id/provision?dry_run=1` returns planned operations.
- Batch provisioning (future): ordered list execution with dependency-aware planning.
- Optical recompute hook:
  - on provisioning of optical-relevant device types.
  - on link create/delete.
  - emits `device.optical.updated` for frontend wiring even if full math path is deferred.

## 8. De-Provision (Deferred)

Deferred in MVP. Target behavior:
- mark device deprovisioned,
- optional IP reclamation policy,
- dependent status recalculation and optical recompute hooks.

## 9. Provisioning API Surface

- `POST /api/devices/:id/provision` -> success payload with updated device state.
- `GET /api/provision/matrix` (planned) -> machine-readable matrix for UI hints.

## 10. Testing Strategy (Minimum)

- Unit:
  - matrix/dependency checks (table-driven).
  - idempotence (`provision` twice -> 409).
  - parent/container rule validation.
- Integration:
  - strict sequence checks (Core -> OLT in POP -> ONT with path requirements).
  - race simulation for concurrent provisioning attempts (single winner).
- Performance:
  - bounded latency under concurrent single-device provision requests.

## 11. Observability

Structured logs:
- `provision.start` with `{device_id, type}`
- `provision.success` with `{pool_key, ip}`
- `provision.failure` with `{reason, code}`

Metrics:
- `provision_success_total{type}`
- `provision_failure_total{reason}`
- Optional `provision_duration_ms`

Note:
- `provisioned=true` may become visible before async status/optical recompute settles.

## 12. Condensed Device -> Parent -> Pool Mapping

| Device Type | Provisionable? | Allowed Parent Container | Upstream Dependency (Strict) | Pool Key | Notes |
| --- | --- | --- | --- | --- | --- |
| Backbone Gateway | implicit seed | none | none | core_mgmt (optional) | optional mgmt IP by flag in future |
| Core Router | yes | none | >=1 Backbone Gateway | core_mgmt | logical upstream provider |
| Router (Edge) | yes | none | >=1 Core Router | core_mgmt | routed node class |
| OLT | yes | POP only | >=1 Core Router | access_mgmt | parent optional, POP-only if set |
| AON Switch | yes | POP only | >=1 Core Router | access_mgmt | parent optional, POP-only if set |
| ONT | yes | none | path to OLT | ont_mgmt | strict only |
| Business ONT | yes | none | path to OLT | ont_mgmt | strict only |
| AON CPE | yes | none | path via AON switch | cpe_mgmt | strict only |
| POP | no | n/a | n/a | n/a | container only |
| Passive Inline | no | n/a | n/a | n/a | non-provisionable |

## 13. Link Type Classification and Rules (Provisioning-Relevant)

Container invariant:
- `POP`/`CORE_SITE` are never link endpoints.

| Rule ID | Endpoint A | Endpoint B | Link Class | Allowed? | Handling | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| L1 | Router-class active | Router-class active | routed_p2p | yes | /31 later | deterministic endpoint order |
| L2 | OLT | Passive Inline | optical_segment | yes | optical attenuation | feeder/distribution chain |
| L3 | Passive Inline | Passive Inline | optical_segment | yes | optical attenuation | chain allowed |
| L4 | Passive Inline | ONT/Business ONT | optical_termination | yes | optical termination | last hop |
| L5 | OLT | ONT | optical_segment | yes (diag) | optical attenuation | lab/direct path |
| L6A | AON Switch | Router-class | access_uplink | yes | logical only | excluded from optical attenuation |
| L6B | OLT | Router-class | access_uplink | yes | logical only | mgmt/aggregation uplink |
| L6 | AON Switch | AON CPE | access_edge | yes | non-optical | access edge path |
| L7 | Active non-OLT | Passive Inline | mixed_invalid | no | reject | invalid composition |
| L8 | ONT/Business ONT | ONT/Business ONT | peer_invalid | no | reject | no ONT peer mesh |
| L9 | Passive Inline | Router-class | reverse_invalid | no | reject | optical semantics violation |

## 14. Runtime Flags (Reference)

| Flag | Default | Scope | Effect |
| --- | --- | --- | --- |
| `ALLOW_RELAXED_UPSTREAM_CHECK` | removed | provisioning | strict-only enforced |
| `STRICT_ONT_ONLINE_ONLY` | planned | status | reserved signal gating control |
| `TRAFFIC_ENABLED` | true (dev) | simulation | periodic metrics on/off |
| `TRAFFIC_TICK_INTERVAL_SEC` | 2.0 | simulation | tick cadence |
| `TRAFFIC_RANDOM_SEED` | unset | simulation | deterministic PRNG seed |
| `TRAFFIC_INJECTION_ENABLED` | true (dev) | simulation debug | enables injection |
| `TRAFFIC_INJECTION_MAX_GBPS` | 10000.0 | simulation debug | injection bound |
| `THRESHOLD_PATH_CACHE_FLUSH_RATIO` | 0.5 | pathfinding | cache flush threshold |
| `UNOC_DEV_FEATURES` | false (prod) | global | dev-only routes/panels |
| `ALLOW_BACKBONE_MGMT_IP` | future | IPAM | optional backbone mgmt assignment |

## 15. Pathfinding Integration Anchor

Canonical algorithm spec remains in `06_future_extensions_and_catalog.md` (pathfinding section).
This provisioning doc defines integration points:
- strict dependency checks use logical upstream graph,
- ONT gating uses selected optical path result,
- topology/attribute mutations invalidate shared path cache.
