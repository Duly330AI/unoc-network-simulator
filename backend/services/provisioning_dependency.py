"""Provisioning dependency gating helpers.

Encapsulates checks that determine whether a device can be provisioned.
"""

from __future__ import annotations

from collections import deque

from sqlmodel import Session, select

from backend.constants import PROVISIONABLE_TYPES
from backend.models import Device, DeviceType, Status
from backend.services import dependency_resolver
from backend.services.dependency_resolver_core import _collect_devices_links
from backend.services.pathfinding import build_optical_graph

_ONT_TYPES = {DeviceType.ONT, DeviceType.BUSINESS_ONT}
_OPTICAL_INLINE_TYPES = {"ODF", "SPLITTER", "NVT", "HOP"}


def _status_is_down(value: object) -> bool:
    return value == Status.DOWN or getattr(value, "value", None) == "DOWN" or str(value) in {
        "DOWN",
        "Status.DOWN",
    }


def _provisioned_upstream_available(device: Device | None) -> bool:
    if device is None or not bool(getattr(device, "provisioned", False)):
        return False
    if _status_is_down(getattr(device, "admin_override_status", None)):
        return False
    return True


def _collect_current_devices_links(session: Session):
    try:
        session.flush()
    except Exception:
        pass
    session.info.pop("_dep_cache", None)
    return _collect_devices_links(session)


def _shortest_path(g, src: str, dst: str) -> list[str] | None:  # type: ignore[no-untyped-def]
    if src not in g or dst not in g:
        return None
    q: deque[tuple[str, tuple[str, ...]]] = deque([(src, (src,))])
    seen = {src}
    while q:
        node, path = q.popleft()
        if node == dst:
            return list(path)
        for nb in sorted(g.neighbors(node)):
            if nb in seen:
                continue
            seen.add(nb)
            q.append((nb, path + (nb,)))
    return None


def has_valid_provisioned_olt_path(session: Session, device: Device) -> bool:
    """Return True when an ONT has optical continuity to a provisioned OLT."""
    if device.type not in _ONT_TYPES:
        return False

    devices, links, _ = _collect_current_devices_links(session)
    optical_graph = build_optical_graph(devices, links)
    if device.id not in optical_graph:
        return False

    allowed_nodes = {
        rec.id
        for rec in devices
        if rec.id == device.id or rec.type == "OLT" or rec.type in _OPTICAL_INLINE_TYPES
    }
    access_graph = optical_graph.subgraph(allowed_nodes)
    candidates: list[tuple[int, tuple[str, ...], str]] = []
    for rec in devices:
        if rec.type != "OLT":
            continue
        olt = session.get(Device, rec.id)
        if not _provisioned_upstream_available(olt):
            continue
        path = _shortest_path(access_graph, device.id, rec.id)
        if path:
            candidates.append((len(path), tuple(path), rec.id))
    candidates.sort()
    return bool(candidates)


def has_valid_provisioned_aon_switch_path(session: Session, device: Device) -> bool:
    """Return True when an AON_CPE has an active direct access edge to a provisioned switch."""
    if device.type != DeviceType.AON_CPE:
        return False

    _devices, links, _ = _collect_current_devices_links(session)
    candidates: list[str] = []
    for link in links:
        if link.a_device_id == device.id:
            other_id = link.b_device_id
        elif link.b_device_id == device.id:
            other_id = link.a_device_id
        else:
            continue
        other = session.get(Device, other_id)
        if other and other.type == DeviceType.AON_SWITCH and _provisioned_upstream_available(other):
            candidates.append(other.id)
    return bool(candidates)


def is_provisionable(device_type: DeviceType) -> bool:
    return device_type in PROVISIONABLE_TYPES


def dependency_ok(session: Session, device: Device) -> bool:
    """Return whether upstream dependency prerequisites are satisfied for provisioning.

    Mirrors the logic previously embedded in the orchestrator for behavioral parity.
    """
    _DT = DeviceType

    if device.type in {_DT.CORE_ROUTER, _DT.EDGE_ROUTER, _DT.BACKBONE_GATEWAY}:
        # Allow creation prior to anchors (anchors may follow). Real status will be DOWN until anchors appear.
        return True

    # Strict access-parent prerequisites.
    if device.type in {_DT.ONT, _DT.BUSINESS_ONT}:
        return has_valid_provisioned_olt_path(session, device)
    if device.type == _DT.AON_CPE:
        return has_valid_provisioned_aon_switch_path(session, device)

    res = dependency_resolver.has_upstream_l3_or_anchor(session, device)
    if res.ok:
        return True
    # Backbone-aware policy:
    # - If a BACKBONE_GATEWAY exists, require full L3 reachability (res.ok)
    # - If not, allow structural router reachability while routers lack L3 to anchor
    #   (tolerate reason routers_no_l3), but reject when there is no router path at all.
    has_backbone = (
        session.exec(select(Device).where(Device.type == _DT.BACKBONE_GATEWAY)).first() is not None
    )
    if not has_backbone:
        reasons = set(getattr(res, "reasons", []) or [])
        if reasons.issubset({"routers_no_l3"}) and device.type in {
            _DT.OLT,
            _DT.AON_SWITCH,
            _DT.ONT,
            _DT.BUSINESS_ONT,
            _DT.AON_CPE,
        }:
            return True
    # Otherwise strict: only routers themselves bypass upstream checks
    return device.type in {_DT.CORE_ROUTER, _DT.EDGE_ROUTER, _DT.BACKBONE_GATEWAY}
