"""Set-link-override implementation extracted from links_helpers.py."""

from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import select

from backend import events
from backend.api.schemas import LinkResolvedOut
from backend.db import get_session, init_db
from backend.models import Device, Interface, Link, Status
from backend.services.event_store import append_write_path_event
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_recompute import recompute_devices_status
from backend.services.status_service import evaluate_device_status, evaluate_link_status

from .links_helpers_common import normalize_status_str

__all__ = ["set_link_override_impl"]


def set_link_override_impl(link_id: str, body: dict) -> LinkResolvedOut:  # type: ignore[no-untyped-def]
    init_db()
    with get_session() as s:
        link = s.get(Link, link_id)
        if not link:
            raise HTTPException(status_code=404, detail="Not found")
        a_iface = s.get(Interface, link.a_interface_id)
        b_iface = s.get(Interface, link.b_interface_id)
        baseline: dict[str, Status] = {}
        all_devs = s.exec(select(Device)).all()
        for dev in all_devs:
            try:
                baseline[dev.id] = evaluate_device_status(dev)
            except Exception:  # pragma: no cover
                continue

        new_val = body.get("admin_override_status", None)
        if new_val is not None and new_val not in {
            Status.UP.value,
            Status.DOWN.value,
            Status.DEGRADED.value,
        }:
            raise HTTPException(status_code=400, detail="Invalid override status")
        link.admin_override_status = Status(new_val) if new_val is not None else None
        s.add(link)
        s.commit()
        append_write_path_event(
            s,
            "LINK_UPDATED",
            link.id,
            {"field": "admin_override_status", "admin_override_status": new_val},
        )
        s.refresh(link)
        try:
            tv = PATHFINDING_STORE.bump_version()
        except Exception:  # pragma: no cover
            tv = None
        eff = evaluate_link_status(link)
        eff_str = normalize_status_str(eff)
        try:
            events.publish(
                events.Event(
                    type="link.override.changed",
                    payload={
                        "id": link.id,
                        "a_interface_id": link.a_interface_id,
                        "b_interface_id": link.b_interface_id,
                        "status": normalize_status_str(link.status),
                        "effective_status": eff_str,
                        "admin_override_status": (
                            normalize_status_str(link.admin_override_status)
                            if link.admin_override_status
                            else None
                        ),
                    },
                    topo_version=tv,
                )
            )
        except Exception:  # pragma: no cover
            pass
        try:
            events.publish(
                events.Event(
                    type="link.status.changed",
                    payload={
                        "id": link.id,
                        "status": normalize_status_str(link.status),
                        "effective_status": eff_str,
                        "admin_override_status": (
                            normalize_status_str(link.admin_override_status)
                            if link.admin_override_status
                            else None
                        ),
                    },
                    topo_version=tv,
                )
            )
        except Exception:  # pragma: no cover
            pass
        try:
            baseline_status_map = {k: v for k, v in baseline.items()}
            recompute_devices_status(s, topo_version=tv, baseline_status=baseline_status_map)
        except Exception:  # pragma: no cover
            pass
        return LinkResolvedOut(
            id=link.id,
            a_interface_id=link.a_interface_id,
            b_interface_id=link.b_interface_id,
            a_device_id=a_iface.device_id if a_iface else "",
            b_device_id=b_iface.device_id if b_iface else "",
            status=link.status,
            effective_status=eff_str,
            kind=link.kind,
            admin_override_status=link.admin_override_status,
            length_km=link.length_km,
            physical_medium_id=link.physical_medium_id,
            rule_id=None,
        )
