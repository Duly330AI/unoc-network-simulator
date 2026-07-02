"""Update-link implementation extracted from links_helpers.py."""

from __future__ import annotations

from fastapi import HTTPException

from backend import events
from backend.api.schemas import LinkResolvedOut, LinkUpdate
from backend.clients.go_services.optical_client import get_optical_client
from backend.clients.go_services.status_client import get_status_client
from backend.db import get_session, init_db
from backend.errors import ErrorCode, raise_error
from backend.link_rules import allowed_media_codes_for_class
from backend.models import Device, Interface, Link, PhysicalMedium, Status
from backend.services.event_store import append_write_path_event
from backend.services.links_service import classify_devices_for_link
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_device_status, evaluate_link_status

from .links_helpers_common import normalize_status_str

__all__ = ["update_link_impl"]


def update_link_impl(link_id: str, payload: LinkUpdate) -> LinkResolvedOut:
    init_db()
    with get_session() as s:
        link = s.get(Link, link_id)
        if not link:
            raise HTTPException(status_code=404, detail="Not found")
        data = payload.model_dump(exclude_unset=True)
        if "length_km" in data and data["length_km"] is not None and data["length_km"] < 0:
            raise HTTPException(status_code=400, detail="length_km must be >= 0")
        if "physical_medium_id" in data and data["physical_medium_id"] is not None:
            if s.get(PhysicalMedium, int(data["physical_medium_id"])) is None:
                raise HTTPException(status_code=400, detail="Invalid physical_medium_id")

        try:
            s.expire_all()
        except Exception:
            pass
        a_iface = s.get(Interface, link.a_interface_id)
        b_iface = s.get(Interface, link.b_interface_id)
        a_dev = s.get(Device, a_iface.device_id) if a_iface else None
        b_dev = s.get(Device, b_iface.device_id) if b_iface else None
        baseline: dict[str, Status] = {}
        for dev in (a_dev, b_dev):
            if dev:
                baseline[dev.id] = evaluate_device_status(dev)

        if (
            "physical_medium_id" in data
            and data["physical_medium_id"] is not None
            and a_dev
            and b_dev
        ):
            cls = classify_devices_for_link(a_dev, b_dev)
            if not cls.allowed:
                raise_error(ErrorCode.INVALID_LINK_TYPE, detail_suffix=cls.rule_id)
            pm_obj = s.get(PhysicalMedium, int(data["physical_medium_id"]))
            if pm_obj is None:
                raise HTTPException(status_code=400, detail="Invalid physical_medium_id")
            allowed = allowed_media_codes_for_class(cls.link_class)
            if allowed and pm_obj.code not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Physical medium '{pm_obj.code}' not allowed for link class "
                        f"'{cls.link_class}' (rule {cls.rule_id})"
                    ),
                )

        for k, v in data.items():
            setattr(link, k, v)
        s.add(link)
        s.commit()
        append_write_path_event(
            s,
            "LINK_UPDATED",
            link.id,
            {"changed_fields": sorted(data.keys())},
        )
        tv = PATHFINDING_STORE.bump_version()
        s.refresh(link)

        try:
            from backend.services import recompute_coalescer as _coalescer

            _coalescer.schedule(scope="links", key=link.id)
        except Exception:  # pragma: no cover
            pass

        try:
            # Optical recompute via Go service (4,000× faster!)
            optical_client = get_optical_client()
            if optical_client:
                optical_client.recompute_paths(link_ids=[link.id])

            events.publish(
                events.Event(
                    type="device.optical.updated",
                    payload={
                        "affected_link_ids": [link.id],
                        "reason": "link_updated",
                    },
                    topo_version=tv,
                )
            )

            # Status propagation via Go service (30,000× faster!)
            try:
                try:
                    s.expire_all()
                except Exception:
                    pass
                affected_ids = list(baseline.keys())
                if affected_ids:
                    status_client = get_status_client()
                    if status_client:
                        status_client.propagate_status(
                            changed_device_ids=affected_ids,
                            changed_link_ids=[link.id],
                            update_database=True,
                        )

                    # Publish status change events for affected devices
                    for dev_id, before in baseline.items():
                        try:
                            cur = s.get(Device, dev_id)
                            if not cur:
                                continue
                            after = evaluate_device_status(cur)
                            if before != after:
                                events.publish(
                                    events.Event(
                                        type="device.status.changed",
                                        payload={
                                            "id": dev_id,
                                            "status": normalize_status_str(after),
                                            "effective_status": normalize_status_str(after),
                                            "admin_override_status": (
                                                normalize_status_str(
                                                    getattr(cur, "admin_override_status", None)
                                                )
                                                if getattr(cur, "admin_override_status", None)
                                                else None
                                            ),
                                        },
                                        topo_version=tv,
                                    )
                                )
                        except Exception:
                            pass
            except Exception:
                pass
            try:
                for dev_id in list(baseline.keys()):
                    cur = s.get(Device, dev_id)
                    if not cur:
                        continue
                    tname = getattr(getattr(cur, "type", None), "name", None)
                    if tname in {"ONT", "BUSINESS_ONT"}:
                        after = evaluate_device_status(cur)
                        events.publish(
                            events.Event(
                                type="device.status.changed",
                                payload={
                                    "id": dev_id,
                                    "status": normalize_status_str(after),
                                    "effective_status": normalize_status_str(after),
                                    "admin_override_status": (
                                        normalize_status_str(
                                            getattr(cur, "admin_override_status", None)
                                        )
                                        if getattr(cur, "admin_override_status", None)
                                        else None
                                    ),
                                },
                                topo_version=tv,
                            )
                        )
            except Exception:
                pass
        except Exception:  # pragma: no cover
            pass

        # NOTE: PON occupancy cache automatically invalidates via provisioning_count
        # No manual invalidation needed - cache reacts to ONT provision state changes

        eff = evaluate_link_status(link)
        eff_str = normalize_status_str(eff)
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
