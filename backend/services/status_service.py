"""Status service (strict-by-default).

Updated status semantics (Design Update Sept 2025):
1. Admin override wins (forced UP/DOWN/BLOCKING) for devices/links.
2. ALWAYS_ONLINE limited to backbone/root containers (BACKBONE_GATEWAY, POP, CORE_SITE).
3. PASSIVE devices (ODF/SPLITTER/HOP/NVT): UP only when forming a valid inline chain with
    at least one upstream active L3-capable path AND at least one downstream terminator; else DOWN.
4. ACTIVE devices (routers, switches, OLT, CPE, ONT variants):
    - Not provisioned -> DOWN.
    - ONT / BUSINESS_ONT with optical NO_SIGNAL -> DOWN.
    - Provisioned and has upstream L3 or anchor (has_upstream_l3_or_anchor.ok) -> UP, sonst DOWN.
    (Previous DEGRADED fallback for missing upstream path removed for clarity.)
"""

from __future__ import annotations

from typing import Any

from backend.models import Device, DeviceRole, DeviceType, Link, Status
from backend.services.status_link import evaluate_link_status, is_link_passable

_get_session = None  # set lazily to avoid import cycles
_eval_upstream = None  # set lazily to avoid import cycles

try:
    from backend.services import status_propagation_store as _prop_store
except Exception:  # pragma: no cover
    _prop_store = None  # fallback if import fails during early init


def evaluate_device_status(device: Device, upstream_cache: dict[str, bool] | None = None) -> Status:
    # Admin override wins (future expansion: MAINTENANCE, etc.)
    if device.admin_override_status:
        return device.admin_override_status
    role = device.derive_role()
    if role in {DeviceRole.ALWAYS_ONLINE}:
        return Status.UP
    if role == DeviceRole.PASSIVE:
        # Delegate PASSIVE evaluation to a helper to keep this module lean.
        try:
            from backend.services.status_service_passive import eval_passive_status  # local import

            return eval_passive_status(device)
        except Exception:
            # On any unexpected resolver error fall back to DEGRADED (signals evaluation issue)
            return Status.DEGRADED
    # Unified ACTIVE device rule (Phase 1 refactor -> Single Source of Truth = L3 connectivity)
    # Applies to all ACTIVE roles (routers, access, OLT, switches, CPE, etc.).
    # Steps:
    #   1. Unprovisioned -> DOWN
    #   2. ONT / BUSINESS_ONT optical NO_SIGNAL -> DOWN regardless of L3
    #   3. Evaluate has_upstream_l3_or_anchor; UP if ok, else DOWN
    if role == DeviceRole.ACTIVE:
        if not device.provisioned:
            return Status.DOWN
        # Optical gating for ONT variants
        if device.type in {DeviceType.ONT, DeviceType.BUSINESS_ONT}:
            try:
                sig = getattr(device, "signal_status", None)
                if sig is not None and (
                    (hasattr(Device, "SignalStatus") and sig == Device.SignalStatus.NO_SIGNAL)
                    or (isinstance(sig, str) and sig == "NO_SIGNAL")
                ):
                    return Status.DOWN
            except Exception:
                # On unexpected attribute issues, fall through to L3 gating (do not elevate to UP)
                pass
        # PERF-005: Check upstream_cache FIRST before opening new session
        if upstream_cache is not None and device.id in upstream_cache:
            # Use cached L3 reachability result
            ok = upstream_cache[device.id]
            return Status.UP if ok else Status.DOWN
        # Fallback: compute L3 reachability (cache miss or no cache provided)
        try:
            from backend.db import get_session as _get_s  # type: ignore
            from backend.services.dependency_resolver import (
                has_l3_reachability_to_anchor as _has_l3_to_anchor,
            )
            from backend.services.dependency_resolver import has_upstream_l3_or_anchor as _has_up_l3

            with _get_s() as _s_dep:  # type: ignore
                # For routers (CORE/EDGE/BACKBONE), directly use the L3 trace-based check
                # to avoid any caching or graph blending discrepancies.
                if device.type in {
                    DeviceType.CORE_ROUTER,
                    DeviceType.EDGE_ROUTER,
                    DeviceType.BACKBONE_GATEWAY,
                }:
                    ok = bool(_has_l3_to_anchor(_s_dep, device))
                    return Status.UP if ok else Status.DOWN
                else:
                    _res = _has_up_l3(_s_dep, device)
                    return Status.UP if getattr(_res, "ok", False) else Status.DOWN
        except Exception:
            # Resolver failure -> conservative DOWN (cannot assert L3 path)
            return Status.DOWN
    return Status.UP

    # Link evaluation utilities are imported from backend.services.status_link


def recompute_dirty(session, dirty, graph=None, cfg=None):
    """Recompute statuses for a dirty set (incremental, deterministic).

    Algorithm (TASK-004):
      1) Build seed set from dirty.devices and endpoints of dirty.links.
      2) Expand to the connected component via cached device adjacency
         (passable, physically viable links + container edges) in a deterministic
         BFS (neighbors and queue kept sorted).
      3) Build a baseline_status map for all affected devices (or use cfg.baseline_status
         if provided) BEFORE applying the new propagation snapshot so that
         `recompute_devices_status` can emit minimal transitions for this change.
      4) Delegate to centralized `recompute_devices_status`, passing topo_version
         for event stamping.

    Returns: list[(device_id, before_str, after_str)].
    """
    try:
        from sqlmodel import select as _select  # type: ignore  # noqa: I001

        from backend.models import Device as _Dev
        from backend.models import Interface as _If
        from backend.models import Link as _Link
        from backend.services.status_recompute import _ensure_graph_cache as _ensure_graph_cache
        from backend.services.status_recompute import (
            recompute_devices_status as _recompute_devices_status,
        )
    except Exception as _imp_err:  # pragma: no cover
        raise _imp_err

    # Helpers
    def _getattr_or_key(obj, name, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    # 1) Seeds: devices + endpoints of dirty links
    seed_devices: list[str] = list(_getattr_or_key(dirty, "devices", []) or [])
    link_ids = list(_getattr_or_key(dirty, "links", []) or [])
    if link_ids:
        rows = session.exec(_select(_Link).where(_Link.id.in_(link_ids))).all()  # type: ignore[attr-defined]
        if rows:
            if_rows = session.exec(_select(_If)).all()
            _if_to_dev = {i.id: i.device_id for i in if_rows}
            for ln in rows:
                a_dev = _if_to_dev.get(ln.a_interface_id)
                b_dev = _if_to_dev.get(ln.b_interface_id)
                if a_dev:
                    seed_devices.append(a_dev)
                if b_dev:
                    seed_devices.append(b_dev)

    # Deterministic seed frontier
    try:
        seeds = sorted({str(x) for x in seed_devices})
    except Exception:
        seeds = sorted({x for x in seed_devices})

    # Metric: observe raw dirty seed size
    try:  # pragma: no cover - optional metric wiring
        from backend.api.endpoints.metrics import DIRTY_SET_SIZE_HISTOGRAM as _DSH

        _DSH.observe(len(seeds))
    except Exception:
        pass

    # Flags / config
    enable_incremental = True
    topo_version = None
    baseline_override = None
    if cfg is not None:
        enable_incremental = bool(getattr(cfg, "enable_incremental", True))
        topo_version = getattr(cfg, "topo_version", None)
        baseline_override = getattr(cfg, "baseline_status", None)

    # Fast path: full recompute when disabled or nothing dirty
    if not enable_incremental or not seeds:
        return _recompute_devices_status(
            session, device_ids=None, topo_version=topo_version, baseline_status=baseline_override
        )

    # 2) Deterministic BFS over cached adjacency to compute affected component
    adjacency, _all_ids = _ensure_graph_cache(session, override_version=topo_version)
    visited: set[str] = set()
    queue: list[str] = list(seeds)  # already sorted
    while queue:
        cur = queue.pop(0)
        if cur in visited:
            continue
        visited.add(cur)
        for nb in sorted(adjacency.get(cur, ())):
            if nb not in visited:
                queue.append(nb)
                if len(queue) > 1 and queue[-2] > queue[-1]:
                    queue.sort()

    affected = sorted(visited)

    # 3) Baseline map (override via cfg when provided)
    if baseline_override is not None:
        baseline = dict(baseline_override)
    else:
        # PERF-004: Batch load all affected devices in single query instead of N+1
        # Previously: session.get() called per device (1001+ calls in profiling)
        # Now: Single query with .in_() filter
        baseline: dict[str, Status] = {}
        if affected:
            # Batch load all devices at once
            devices_batch = session.exec(
                _select(_Dev).where(_Dev.id.in_(affected))  # type: ignore[attr-defined]
            ).all()
            # Build map for O(1) lookup
            dev_map = {d.id: d for d in devices_batch}

            # PERF-005: Pre-compute upstream L3 reachability for all affected devices
            # to avoid 663 recursive has_upstream_l3_or_anchor() calls (0.68s + queries)
            upstream_cache: dict[str, bool] = {}
            try:
                from backend.services.dependency_resolver import (
                    has_upstream_l3_or_anchor as _has_up_l3,
                )

                for did, dev in dev_map.items():
                    if dev.derive_role() == DeviceRole.ACTIVE:
                        try:
                            _res = _has_up_l3(session, dev)
                            upstream_cache[did] = getattr(_res, "ok", False)
                        except Exception:
                            upstream_cache[did] = False
            except Exception:
                # If dependency resolver unavailable, proceed without cache
                pass

            # Evaluate status for each device (now passes upstream_cache to avoid recursive queries)
            for did in affected:
                dev = dev_map.get(did)
                if dev is None:
                    continue
                try:
                    baseline[did] = evaluate_device_status(dev, upstream_cache=upstream_cache)
                except Exception:
                    # On any evaluation error, skip baseline for this device so no false transition is emitted
                    continue

    # 4) Delegate to centralized recompute (events + snapshot + transitions)
    return _recompute_devices_status(
        session,
        device_ids=affected,
        topo_version=topo_version,
        baseline_status=baseline,
    )


__all__ = [
    "evaluate_device_status",
    "evaluate_link_status",
    "is_link_passable",
    "recompute_dirty",
    "detect_causal_chain_python",  # Python fallback for Go service
    "bulk_update_device_statuses",  # Python fallback for Go service
]


# =============================================================================
# Python Fallback Functions for Go Status Propagation Service
# =============================================================================
# These functions provide a Python implementation of causal chain detection
# when the Go service is unavailable. Performance is ~30,000× slower
# (2000ms vs 66μs) but functionally equivalent.


def detect_causal_chain_python(
    changed_device_ids: list[str],
    changed_link_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Python implementation of causal chain detection.

    Used as fallback when Go Status Propagation Service unavailable.

    NOTE: This is significantly slower (~2000ms vs 66μs) but
    functionally equivalent to the Go implementation.

    Args:
        changed_device_ids: List of device IDs that changed status
        changed_link_ids: List of link IDs that changed status (optional)

    Returns:
        Dict with keys:
            - affected_devices: List[str] (device IDs affected by change)
            - affected_links: List[str] (link IDs affected, empty for now)
            - dependency_paths: Dict[str, List[str]] (device_id -> upstream path)
    """
    from collections.abc import Sequence

    from sqlmodel import select

    from backend.db import get_session
    from backend.models import Device, Link

    changed_link_ids = changed_link_ids or []

    with get_session() as session:
        # 1. Build dependency graph
        devices: Sequence[Device] = session.exec(select(Device)).all()
        links: Sequence[Link] = session.exec(select(Link)).all()

        graph = _build_dependency_graph_python(list(devices), list(links))

        # 2. BFS traversal from changed devices
        visited: set[str] = set()
        queue: list[str] = list(changed_device_ids)
        paths: dict[str, list[str]] = {did: [did] for did in changed_device_ids}

        while queue:
            current_id = queue.pop(0)

            if current_id in visited:
                continue
            visited.add(current_id)

            # Get device
            device = next((d for d in devices if d.id == current_id), None)
            if not device:
                continue

            # Check if device can propagate status
            if not _is_device_up_candidate_python(device):
                continue  # Stop propagation at this node

            # Get downstream dependencies
            for downstream_id in graph.get(current_id, []):
                if downstream_id not in visited:
                    queue.append(downstream_id)
                    # Track dependency path
                    paths[downstream_id] = paths[current_id] + [downstream_id]

        return {
            "affected_devices": list(visited),
            "affected_links": [],  # TODO: implement link propagation
            "dependency_paths": paths,
        }


def _build_dependency_graph_python(
    devices: list[Device],
    links: list[Link],
) -> dict[str, list[str]]:
    """
    Build dependency graph (device_id -> downstream device_ids).

    Args:
        devices: All devices in topology
        links: All links in topology

    Returns:
        Dict mapping device_id -> list of downstream device_ids
    """

    # Build interface -> device mapping
    interface_to_device: dict[str, str] = {}
    for device in devices:
        # Load interfaces relationship if not already loaded
        from sqlmodel import select

        from backend.db import get_session
        from backend.models import Interface

        with get_session() as session:
            interfaces = session.exec(
                select(Interface).where(Interface.device_id == device.id)
            ).all()
            for interface in interfaces:
                interface_to_device[interface.id] = device.id

    # Build adjacency graph
    graph: dict[str, list[str]] = {}

    for link in links:
        # Skip if link not passable
        if not _is_link_passable_python(link):
            continue

        # Get device IDs from interfaces
        a_device_id = interface_to_device.get(link.a_interface_id)
        b_device_id = interface_to_device.get(link.b_interface_id)

        if not a_device_id or not b_device_id:
            continue

        # Bidirectional edges (status propagates both ways)
        if a_device_id not in graph:
            graph[a_device_id] = []
        if b_device_id not in graph:
            graph[b_device_id] = []

        graph[a_device_id].append(b_device_id)
        graph[b_device_id].append(a_device_id)

    return graph


def _is_device_up_candidate_python(device: Device) -> bool:
    """
    Check if device can be UP (eligible for status propagation).

    Args:
        device: Device to check

    Returns:
        True if device can be UP, False otherwise
    """
    # Admin override blocks propagation
    if device.admin_override_status:
        return False

    # Unprovisioned ACTIVE devices block propagation
    role = device.derive_role()
    if role == DeviceRole.ACTIVE and not device.provisioned:
        return False

    # Standby devices can still propagate
    # (they exist in dependency tree)
    return True


def _is_link_passable_python(link: Link) -> bool:
    """
    Check if link allows status propagation.

    Args:
        link: Link to check

    Returns:
        True if link allows propagation, False otherwise
    """
    # Use existing is_link_passable() logic from status_link module
    return is_link_passable(link)


def bulk_update_device_statuses(device_ids: list[str]) -> None:
    """
    Bulk update device statuses in database.

    Args:
        device_ids: List of device IDs to update

    Side Effects:
        Updates device.status in database for all affected devices
    """
    from sqlmodel import select

    from backend.db import get_session
    from backend.models import Device
    from backend.services.event_store_runtime import projection_write_context

    # Internal derived-state writer (status propagation fallback); explicitly
    # excluded from the EventStore bypass guard.
    with projection_write_context(), get_session() as session:
        # Batch load all devices
        devices = session.exec(select(Device).where(Device.id.in_(device_ids))).all()  # type: ignore[attr-defined]

        # Recompute status for each device
        changed = False
        for device in devices:
            try:
                new_status = evaluate_device_status(device)
                if device.status != new_status:
                    device.status = new_status
                    changed = True
            except Exception:
                # Skip device on evaluation error
                continue

        session.commit()
        if changed:
            try:
                from backend.api.endpoints.devices_helpers_query import bump_devices_cache_epoch

                bump_devices_cache_epoch("status_bulk_update")
            except Exception:
                pass
