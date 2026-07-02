"""Delete-link implementation extracted from links_helpers.py."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend import events
from backend.clients.go_services.optical_client import get_optical_client
from backend.clients.go_services.status_client import get_status_client
from backend.db import get_session, init_db
from backend.models import Device, Interface, Link
from backend.services.event_store import append_write_path_event
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_device_status

__all__ = ["delete_link_impl"]


def delete_link_impl(link_id: str) -> None:
    init_db()
    with get_session() as s:
        link = s.get(Link, link_id)
        if not link:
            raise HTTPException(status_code=404, detail="Not found")
        a_iface = s.get(Interface, link.a_interface_id)
        b_iface = s.get(Interface, link.b_interface_id)
        a_dev = s.get(Device, a_iface.device_id) if a_iface else None
        b_dev = s.get(Device, b_iface.device_id) if b_iface else None
        baseline: dict[str, Any] = {}
        for dev in (a_dev, b_dev):
            if dev:
                baseline[dev.id] = evaluate_device_status(dev)
        s.delete(link)
        s.commit()
        append_write_path_event(
            s,
            "LINK_DELETED",
            link_id,
            {
                "a_interface_id": a_iface.id if a_iface else None,
                "b_interface_id": b_iface.id if b_iface else None,
            },
        )
        tv = PATHFINDING_STORE.bump_version()

        events.publish(events.Event(type="link.deleted", payload={"id": link_id}, topo_version=tv))
        try:
            from backend.services import recompute_coalescer as _coalescer

            _coalescer.schedule(scope="links", key=link_id)
        except Exception:  # pragma: no cover
            pass
        try:
            # Optical recompute via Go service (4,000× faster!)
            optical_client = get_optical_client()
            if optical_client:
                optical_client.recompute_paths(link_ids=[link_id])

            optical_evt = events.Event(
                type="device.optical.updated",
                payload={
                    "affected_link_ids": [link_id],
                    "reason": "link_deleted",
                },
                topo_version=tv,
            )
            events.publish(optical_evt)

            # Status propagation via Go service (30,000× faster!)
            affected_device_ids = []
            if a_dev:
                affected_device_ids.append(a_dev.id)
            if b_dev:
                affected_device_ids.append(b_dev.id)

            if affected_device_ids:
                status_client = get_status_client()
                if status_client:
                    status_client.propagate_status(
                        changed_device_ids=affected_device_ids,
                        changed_link_ids=[link_id],
                        update_database=True,
                    )
        except Exception as e:  # pragma: no cover
            print(f"[WARN] Go service call failed after link delete: {e}")

        # NOTE: PON occupancy cache automatically invalidates via provisioning_count
        # No manual invalidation needed - cache reacts to ONT provision state changes

        return None
