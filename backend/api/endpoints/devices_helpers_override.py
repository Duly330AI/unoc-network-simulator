"""Helper for devices override endpoint.

Side-effecting: writes device admin_override_status, emits event on change,
and schedules recompute. Keep deterministic ordering/semantics.
"""

from __future__ import annotations

from sqlmodel import Session

from backend import events
from backend.api.schemas import DeviceOut
from backend.models import Device, Status
from backend.services.event_store import append_write_path_event
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_device_status


def set_device_override_impl(s: Session, device_id: str, body: dict) -> DeviceOut:  # type: ignore[no-untyped-def]
    d = s.get(Device, device_id)
    if not d:
        raise LookupError("Not found")
    before = evaluate_device_status(d)
    new_val = body.get("admin_override_status", None)
    if new_val is not None and new_val not in {
        Status.UP.value,
        Status.DOWN.value,
        Status.DEGRADED.value,
    }:
        raise ValueError("Invalid override status")
    d.admin_override_status = Status(new_val) if new_val is not None else None
    s.add(d)
    s.commit()
    append_write_path_event(
        s,
        "DEVICE_UPDATED",
        d.id,
        {"field": "admin_override_status", "admin_override_status": new_val},
    )
    tv = PATHFINDING_STORE.bump_version()
    s.refresh(d)
    after = evaluate_device_status(d)
    if before != after:
        events.publish(
            events.Event(
                type="device.status.changed",
                payload={
                    "id": d.id,
                    "status": str(after),
                    "effective_status": str(after),
                    "admin_override_status": (
                        str(d.admin_override_status) if d.admin_override_status else None
                    ),
                },
                topo_version=tv,
            )
        )
    try:
        from backend.services import recompute_coalescer as _coalescer

        _coalescer.schedule(scope="devices", key=d.id)
    except Exception:
        pass
    return DeviceOut.from_model(d)
