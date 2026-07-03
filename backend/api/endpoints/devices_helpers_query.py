"""Query helpers for devices endpoints.

Pure read-only utilities used by the FastAPI route handlers in devices.py.
"""

from __future__ import annotations

import hashlib
import json
from threading import Lock

from sqlmodel import Session, select

from backend.api.schemas import DeviceOut
from backend.models import Device
from backend.services.count_semantics import count_semantics_for
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.subscriber_model import resolve_subscriber_model, subscriber_parameters

from .devices_helpers_common import resolve_vrf_name_map, serialize_interfaces_for_device

# Topology-versioned in-process cache for list_devices_impl results.
# Keyed by (topology_version, cache_epoch, include_interfaces)
_DEVICES_CACHE: dict[tuple[int, int, bool], list[DeviceOut]] = {}
_DEVICES_CACHE_LOCK = Lock()
_DEVICES_CACHE_EPOCH = 0

# Pre-serialized JSON cache (bytes) and ETag per (topology_version, cache_epoch, include_interfaces)
_DEVICES_JSON_CACHE: dict[tuple[int, int, bool], tuple[bytes, str]] = {}


def _devices_cache_epoch() -> int:
    with _DEVICES_CACHE_LOCK:
        return _DEVICES_CACHE_EPOCH


def bump_devices_cache_epoch(reason: str | None = None) -> int:
    """Invalidate /api/devices caches after derived device fields change."""
    del reason  # reserved for future debug logging
    global _DEVICES_CACHE_EPOCH
    with _DEVICES_CACHE_LOCK:
        _DEVICES_CACHE_EPOCH += 1
        _DEVICES_CACHE.clear()
        _DEVICES_JSON_CACHE.clear()
        return _DEVICES_CACHE_EPOCH


def _attach_subscriber_parameters(device_out: DeviceOut, model: dict, count_model: dict | None = None) -> None:
    dev_type = str(getattr(device_out.type, "value", device_out.type) or "").upper()
    if dev_type not in {"OLT", "AON_SWITCH", "ONT", "BUSINESS_ONT", "AON_CPE"}:
        return
    subscribers = subscriber_parameters(model, device_out.id)
    count_semantics = count_semantics_for(count_model or {}, device_out.id)
    effective_count = count_semantics.get("effective_count", subscribers.get("total"))
    params = dict(device_out.parameters or {})
    params["subscribers"] = subscribers
    params["count_semantics"] = count_semantics
    device_out.parameters = params
    device_out.subscribers = int(effective_count or 0)


_PASSIVE_OPTICAL_TYPES = {"SPLITTER", "HOP", "NVT", "ODF"}


def _attach_measured_optical_loss(device_out: DeviceOut, optical_state: dict) -> None:
    """Expose L1 measured loss to consumers for passive optical devices.

    Configured insertion_loss_db may be unset while the optical physics model has a
    real computed loss; the UI must not display 0.0 dB / "-" in that case.
    """
    dev_type = str(getattr(device_out.type, "value", device_out.type) or "").upper()
    if dev_type not in _PASSIVE_OPTICAL_TYPES:
        return
    entry = (optical_state.get("devices") or {}).get(device_out.id) or {}
    measured = entry.get("measured_loss_db")
    if measured is None:
        return
    params = dict(device_out.parameters or {})
    optical = dict(params.get("optical") or {})
    optical["measured_loss_db"] = measured
    optical["measured_loss_source"] = "L1_OPTICAL_PHYSICS"
    params["optical"] = optical
    device_out.parameters = params


def list_devices_impl(s: Session, include_interfaces: bool) -> list[DeviceOut]:
    tv = PATHFINDING_STORE.version()
    epoch = _devices_cache_epoch()
    key = (tv, epoch, bool(include_interfaces))
    cached = _DEVICES_CACHE.get(key)
    if cached is not None:
        return cached

    # Build fresh and populate cache under lock (double-checked)
    with _DEVICES_CACHE_LOCK:
        cached = _DEVICES_CACHE.get(key)
        if cached is not None:
            return cached

        devices = s.exec(select(Device)).all()
        subscriber_model = resolve_subscriber_model(s)
        from backend.services.count_semantics import build_count_semantics
        from backend.services.optical_physics_model import resolve_optical_physics_state

        count_model = build_count_semantics(s)
        optical_state = resolve_optical_physics_state(s)
        vrf_name_map = resolve_vrf_name_map(s, devices)
        out: list[DeviceOut] = []
        for d in devices:
            o = DeviceOut.from_model(d)
            _attach_subscriber_parameters(o, subscriber_model, count_model)
            _attach_measured_optical_loss(o, optical_state)
            vid = getattr(d, "vrf_id", None)
            if vid is not None:
                o.device_default_vrf_name = vrf_name_map.get(int(vid))
            out.append(o)
        if include_interfaces:
            for d_out in out:
                d_out.interfaces = serialize_interfaces_for_device(s, d_out.id)

        _DEVICES_CACHE[key] = out
        # Opportunistic cleanup to cap memory: drop entries for older topo versions
        old_keys = [k for k in _DEVICES_CACHE.keys() if k[0] != tv or k[1] != epoch]
        for k in old_keys:
            _DEVICES_CACHE.pop(k, None)
        return out


def _serialize_devices_to_json(devs: list[DeviceOut]) -> bytes:
    # Use a stable JSON representation; exclude None to match response_model_exclude_none
    # Convert models to dicts to avoid re-validating with FastAPI; DeviceOut is pydantic model
    arr = [d.model_dump(exclude_none=True) for d in devs]
    # Compact separators for smaller payload and deterministic bytes
    return json.dumps(arr, separators=(",", ":"), sort_keys=False).encode("utf-8")


def _compute_etag(tv: int, epoch: int, include_interfaces: bool, payload: bytes) -> str:
    h = hashlib.sha256()
    h.update(b"tv=")
    h.update(str(tv).encode())
    h.update(b";epoch=")
    h.update(str(epoch).encode())
    h.update(b";if=")
    h.update(b"1" if include_interfaces else b"0")
    h.update(b";payload=")
    h.update(payload)
    # Weak ETag format is fine; include short prefix for readability
    return 'W/"tv:%d-epoch:%d-if:%d-%s"' % (
        tv,
        epoch,
        1 if include_interfaces else 0,
        h.hexdigest()[:16],
    )


def get_devices_json_cached(s: Session, include_interfaces: bool) -> tuple[bytes, str]:
    """Return (json_bytes, etag) for devices list, cached by topology version and epoch.

    Builds from the existing object cache to avoid duplicate DB queries.
    """
    tv = PATHFINDING_STORE.version()
    epoch = _devices_cache_epoch()
    key = (tv, epoch, bool(include_interfaces))
    cached = _DEVICES_JSON_CACHE.get(key)
    if cached is not None:
        return cached

    # Ensure objects exist (will populate _DEVICES_CACHE as needed)
    objs = list_devices_impl(s, include_interfaces)
    payload = _serialize_devices_to_json(objs)
    etag = _compute_etag(tv, epoch, bool(include_interfaces), payload)
    with _DEVICES_CACHE_LOCK:
        if key not in _DEVICES_JSON_CACHE:
            _DEVICES_JSON_CACHE[key] = (payload, etag)
            # Cleanup old versions to bound memory
            old_keys = [k for k in _DEVICES_JSON_CACHE.keys() if k[0] != tv or k[1] != epoch]
            for k in old_keys:
                _DEVICES_JSON_CACHE.pop(k, None)
    return _DEVICES_JSON_CACHE.get(key, (payload, etag))


def get_device_impl(s: Session, device_id: str) -> DeviceOut:
    d = s.get(Device, device_id)
    if not d:
        raise LookupError("Not found")
    o = DeviceOut.from_model(d)
    subscriber_model = resolve_subscriber_model(s)
    from backend.services.count_semantics import build_count_semantics
    from backend.services.optical_physics_model import resolve_optical_physics_state

    _attach_subscriber_parameters(o, subscriber_model, build_count_semantics(s))
    _attach_measured_optical_loss(o, resolve_optical_physics_state(s))
    vid = getattr(d, "vrf_id", None)
    if vid is not None:
        from backend.models import VRF  # local import to avoid circulars at import time

        v = s.get(VRF, int(vid))
        o.device_default_vrf_name = v.name if v else None
    return o
