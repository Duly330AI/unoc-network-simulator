"""Central status recompute utility (strict-by-default).

Evaluates dynamic device status for a set of devices (or all devices) using
`evaluate_device_status` and emits `device.status.changed` events for any
transitions detected. The caller can pass a `topo_version` so emitted events
share the same version as the surrounding topology change.

Always computes reachability propagation across links/containers and updates
the global snapshot store used by status_service.
"""

from __future__ import annotations

import time as _time
from collections.abc import Iterable, Mapping, Sequence
from threading import RLock

from sqlmodel import Session, select

from backend import events
from backend.clients.go_services.status_client import get_status_client
from backend.models import Device, DeviceRole, Link, Status
from backend.services import status_diagnostics as _diag
from backend.services import status_propagation_store as propagation_store
from backend.services.dependency_resolver import has_upstream_l3_or_anchor
from backend.services.link_validator_service import is_link_physically_viable
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_device_status


def _prop_enabled() -> bool:
    # Always enabled in strict-by-default mode.
    return True


_GRAPH_LOCK = RLock()
_GRAPH_CACHE: dict[str, object] = {
    "version": -1,
    "override_fp": None,
    # Cached undirected adjacency across passable, physically viable links
    "adjacency": None,  # type: ignore[assignment]
    # Cached ordered device id list (snapshot bookkeeping)
    "device_ids": None,  # type: ignore[assignment]
    # Cached rows to avoid repeated ORM fetch when topology is unchanged
    "_all_devices": None,  # type: ignore[assignment]
    # Cached Interface -> Device map for fast adjacency build
    "_if_to_dev": None,  # type: ignore[assignment]
}


def _ensure_graph_cache(
    session: Session, override_version: int | None = None
) -> tuple[dict[str, set[str]], list[str]]:
    """Return topology-versioned adjacency ready for propagation BFS.

    Caches the undirected device adjacency (across passable, physically viable links)
    and the list of all device IDs for snapshot bookkeeping. Invalidates when
    PATHFINDING_STORE.version() changes (link create/update/delete or override where wired).
    """
    # Prefer caller-provided version (from topology change context) when available.
    # This ensures admin overrides and test-driven topo versions trigger cache refreshes
    # even if the central PATHFINDING_STORE.version() hasn't changed yet.
    topo_v = override_version if override_version is not None else PATHFINDING_STORE.version()

    def _override_fp() -> tuple[int, int, int, int]:
        try:
            from backend.models import Link as _Link

            dev_rows = session.exec(select(Device)).all()
            link_rows = session.exec(select(_Link)).all()
            n_dev_up = 0
            n_dev_down = 0
            for d in dev_rows:
                v = getattr(d, "admin_override_status", None)
                if v is None:
                    continue
                if (hasattr(v, "value") and v.value == "UP") or (
                    not hasattr(v, "value") and str(v) == "UP"
                ):
                    n_dev_up += 1
                elif (hasattr(v, "value") and v.value == "DOWN") or (
                    not hasattr(v, "value") and str(v) == "DOWN"
                ):
                    n_dev_down += 1
            n_link_up = 0
            n_link_down = 0
            for ln in link_rows:
                v = getattr(ln, "admin_override_status", None)
                if v is None:
                    continue
                if (hasattr(v, "value") and v.value == "UP") or (
                    not hasattr(v, "value") and str(v) == "UP"
                ):
                    n_link_up += 1
                elif (hasattr(v, "value") and v.value == "DOWN") or (
                    not hasattr(v, "value") and str(v) == "DOWN"
                ):
                    n_link_down += 1
            return (n_dev_up, n_dev_down, n_link_up, n_link_down)
        except Exception:
            return (-1, -1, -1, -1)

    with _GRAPH_LOCK:
        # Fast path: reuse cached structures when topology version matches
        cached_v = _GRAPH_CACHE.get("version", -2)
        cached_fp = _GRAPH_CACHE.get("override_fp")
        cur_fp = _override_fp()
        if (
            cached_v == topo_v
            and cached_fp == cur_fp
            and _GRAPH_CACHE.get("adjacency") is not None
            and _GRAPH_CACHE.get("device_ids") is not None
        ):
            return _GRAPH_CACHE["adjacency"], _GRAPH_CACHE["device_ids"]  # type: ignore[return-value]

        # Slow path: rebuild from current DB state
        adjacency: dict[str, set[str]] = {}
        links = session.exec(select(Link)).all()
        from backend.models import Interface  # local import to avoid cycle in imports
        from backend.services.status_service import (
            is_link_passable as _is_link_passable,  # local import to avoid cycles
        )

        # Build interface->device map once to avoid repeated lookups; cache it per topo version
        if_rows = session.exec(select(Interface)).all()
        if_to_dev = {i.id: i.device_id for i in if_rows}

        for ln in links:
            try:
                if not _is_link_passable(ln):
                    continue
            except Exception:
                continue
            if not is_link_physically_viable(session, ln):
                continue
            a_dev = if_to_dev.get(ln.a_interface_id)
            b_dev = if_to_dev.get(ln.b_interface_id)
            if not a_dev or not b_dev:
                continue
            adjacency.setdefault(a_dev, set()).add(b_dev)
            adjacency.setdefault(b_dev, set()).add(a_dev)
        # Also add container adjacency edges (parent_container_id relationships)
        all_devices = session.exec(select(Device)).all()
        for d in all_devices:
            parent = getattr(d, "parent_container_id", None)
            if parent:
                adjacency.setdefault(d.id, set()).add(parent)
                adjacency.setdefault(parent, set()).add(d.id)

        # Update cache fields for observability only (not used for early-return)
        _GRAPH_CACHE["version"] = topo_v
        _GRAPH_CACHE["override_fp"] = cur_fp
        _GRAPH_CACHE["adjacency"] = adjacency
        _GRAPH_CACHE["device_ids"] = [d.id for d in all_devices]
        _GRAPH_CACHE["_all_devices"] = list(all_devices)
        _GRAPH_CACHE["_if_to_dev"] = dict(if_to_dev)
        return adjacency, _GRAPH_CACHE["device_ids"]  # type: ignore[return-value]


def recompute_devices_status(
    session: Session,
    device_ids: Iterable[str] | None = None,
    *,
    include_passive_propagation: bool = False,
    topo_version: int | None = None,
    baseline_status: Mapping[str, Status] | None = None,
) -> list[tuple[str, str, str]]:
    """Recompute dynamic status for given devices and emit transitions.

    Args:
        session: Active SQLModel session.
        device_ids: Set/iterable of device ids to recompute. If None, recompute all.
        include_passive_propagation: Ignored in Phase 1; placeholder for Phase 2.
        topo_version: Optional topology version to stamp on events.

    Returns:
        List of tuples (device_id, before_str, after_str) for transitioned devices.
    """
    devices: Sequence[Device]
    _phase_t = _time.perf_counter()
    if device_ids is None:
        devices = session.exec(select(Device)).all()
    else:
        # Preserve order for determinism in tests by materializing ids
        ids = list(device_ids)
        tmp: list[Device | None] = [session.get(Device, did) for did in ids]
        devices = [d for d in tmp if d is not None]
    # Phase timing: data_fetching
    try:
        from backend.api.endpoints.metrics import STATUS_RECOMPUTE_PHASE_DURATION as _PH

        _PH.labels(phase="data_fetching").observe(_time.perf_counter() - _phase_t)
    except Exception:
        pass

    transitions: list[tuple[str, str, str]] = []
    _t0 = _time.perf_counter()
    # Always compute global snapshot first
    _phase_t = _time.perf_counter()
    adjacency, seen_device_ids = _ensure_graph_cache(session, override_version=topo_version)
    # Phase timing: graph_building
    try:
        from backend.api.endpoints.metrics import STATUS_RECOMPUTE_PHASE_DURATION as _PH

        _PH.labels(phase="graph_building").observe(_time.perf_counter() - _phase_t)
    except Exception:
        pass
    # Identify seeds (anchors for reachability):
    # - If the topology contains any BACKBONE_GATEWAY devices, use ONLY those
    #   BACKBONE_GATEWAY devices that are not overridden DOWN as seeds.
    # - Otherwise, fall back to all ALWAYS_ONLINE devices (e.g., POP) that are not overridden DOWN.
    seeds: set[str] = set()
    all_devices = session.exec(select(Device)).all()
    has_backbone_anchor = any(d.type.name == "BACKBONE_GATEWAY" for d in all_devices)
    for dev in all_devices:
        role = dev.derive_role()
        if role == DeviceRole.ALWAYS_ONLINE:
            if has_backbone_anchor and dev.type.name != "BACKBONE_GATEWAY":
                continue
            # Respect admin override: only seed if effective candidate is UP
            if (
                getattr(dev, "admin_override_status", None) is None
                or dev.admin_override_status == Status.UP
            ):
                seeds.add(dev.id)

    def _is_up_candidate(d: Device) -> bool:
        """Device can participate in reachability (acts as conduit).

        Rules:
        - Admin override DOWN => not a candidate
        - ALWAYS_ONLINE => candidate
        - PASSIVE => candidate
        - ACTIVE => candidate only when provisioned
        """
        if (
            getattr(d, "admin_override_status", None) is not None
            and d.admin_override_status != Status.UP
        ):
            return False
        r = d.derive_role()
        if r in {DeviceRole.ALWAYS_ONLINE, DeviceRole.PASSIVE}:
            return True
        if r == DeviceRole.ACTIVE:
            return bool(getattr(d, "provisioned", False))
        return False

    # BFS flood from seeds across adjacency (legacy propagation) – retained only
    # for comparability during Phase 1 instrumentation.
    _phase_t = _time.perf_counter()

    # Try GO service first (30,000× speedup: 2000ms → 66μs)
    status_client = get_status_client()
    go_success = False

    if status_client._go_available:
        try:
            # Collect changed device/link IDs from context (if any)
            changed_device_ids = list(device_ids) if device_ids else []
            changed_link_ids: list[str] = []  # TODO: Extract from context if available

            # Call GO service for status propagation
            result = status_client.propagate_status(
                changed_device_ids=changed_device_ids,
                changed_link_ids=changed_link_ids,
                update_database=False,  # We'll handle DB updates in Python for now
            )

            if result.get("status") == "success":
                # Use GO service results
                reachable = set(result.get("reachable_device_ids", []))
                go_success = True
        except Exception as e:
            # Fall back to Python BFS
            print(f"⚠️ GO status service failed: {e}, using Python BFS fallback")

    # Python BFS fallback (or if GO not available)
    if not go_success:
        reachable: set[str] = set(seeds)
        queue = sorted(list(seeds))  # deterministic order
        while queue:
            cur_id = queue.pop(0)
            for nb in sorted(adjacency.get(cur_id, ())):  # neighbors in deterministic order
                if nb in reachable:
                    continue
                nb_dev = session.get(Device, nb)
                if not nb_dev:
                    continue
                if _is_up_candidate(nb_dev):
                    reachable.add(nb)
                    # maintain sorted queue insertion for stable traversal
                    queue.append(nb)
                    if len(queue) > 1 and queue[-2] > queue[-1]:
                        queue.sort()

    # Phase timing: propagation
    try:
        from backend.api.endpoints.metrics import STATUS_RECOMPUTE_PHASE_DURATION as _PH

        _PH.labels(phase="propagation").observe(_time.perf_counter() - _phase_t)
    except Exception:
        pass

    # Update snapshot store
    propagation_store.set_snapshot(reachable, seen_device_ids=seen_device_ids)
    # Phase 1 instrumentation (Commit 1): populate minimal diagnostics without changing
    # existing status semantics.
    try:
        for dev in all_devices:
            legacy_reach = dev.id in reachable
            res = has_upstream_l3_or_anchor(session, dev)
            _diag.set_device_diag(
                dev.id,
                upstream_l3_ok=res.ok,
                anchor=res.anchor,
                chain=res.chain,
                reason_codes=res.reasons,
                legacy_bfs_reachable=legacy_reach,
            )
    except Exception:
        # Diagnostics must never break recompute; swallow errors (can log later).
        pass
    # Preserve the evaluated device set determined above. When called from
    # recompute_dirty, this contains only the affected devices; if the caller
    # passed device_ids=None, it already contains all devices.

    _phase_t = _time.perf_counter()
    for d in devices:
        before_status = baseline_status.get(d.id) if baseline_status is not None else None
        before = before_status if before_status is not None else evaluate_device_status(d)
        # Reload latest
        cur = session.get(Device, d.id) or d
        after = evaluate_device_status(cur)
        if before != after:
            transitions.append((d.id, str(before), str(after)))
            evt = events.Event(
                type="device.status.changed",
                payload={
                    "id": d.id,
                    "status": getattr(after, "value", str(after)).split(".")[-1],
                    # Include effective_status explicitly so frontend can react without full refetch.
                    "effective_status": getattr(after, "value", str(after)).split(".")[-1],
                    "admin_override_status": (
                        getattr(
                            getattr(cur, "admin_override_status", None),
                            "value",
                            str(getattr(cur, "admin_override_status", None)),
                        ).split(".")[-1]
                        if getattr(cur, "admin_override_status", None)
                        else None
                    ),
                },
                topo_version=topo_version,
            )
            events.publish(evt)
    if transitions:
        from backend.services.status_service import bulk_update_device_statuses

        bulk_update_device_statuses(
            [device_id for device_id, _before, _after in transitions]
        )
        session.expire_all()
    # Phase timing: db_update (approximate: includes status evaluation and event publication)
    try:
        from backend.api.endpoints.metrics import STATUS_RECOMPUTE_PHASE_DURATION as _PH

        _PH.labels(phase="db_update").observe(_time.perf_counter() - _phase_t)
    except Exception:
        pass
    # Observe recompute duration (import lazily to avoid cycles)
    try:
        from backend.api.endpoints.metrics import STATUS_RECOMPUTE_DURATION as _RECOMP_HIST

        _RECOMP_HIST.observe(_time.perf_counter() - _t0)
    except Exception:
        pass
    return transitions


__all__ = ["recompute_devices_status"]
