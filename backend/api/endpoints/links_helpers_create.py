"""Create-link implementation extracted from links_helpers.py.

Kept behavior identical; imported and re-exported by links_helpers.py to
preserve the public API for routes and tests.
"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from backend import events
from backend.api.schemas import LinkCreate, LinkResolvedOut
from backend.clients.go_services.optical_client import get_optical_client
from backend.clients.go_services.status_client import get_status_client
from backend.constants import ONT_CLASS, PASSIVE_INLINE
from backend.db import get_session, init_db
from backend.errors import ErrorCode, raise_error
from backend.link_rules import allowed_media_codes_for_class
from backend.models import Device, Interface, Link, PhysicalMedium
from backend.services import recompute_coalescer as coalescer
from backend.services.event_store import append_write_path_event
from backend.services.link_policy_optical import (
    enforce_ont_placement_rules,
    enforce_pon_role_if_declared,
    enforce_single_upstream_rules,
)
from backend.services.links_service import (
    canonical_link_id,
    classify_devices_for_link,
    derive_default_length_km,
    pick_default_physical_medium_id,
)
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_link_status
from backend.utils import ensure_default_interface

from .links_helpers_common import normalize_status_str

__all__ = ["create_link_impl"]


def _dev_from_iface_id(s, iid: str) -> str | None:
    """Best-effort device-id inference for a given interface-id.

    Prefers existing Interface lookup, then '-if0' convention, then a
    conservative '<device>-<port>' split if the device exists.
    """
    iface = s.get(Interface, iid)
    if iface is not None:
        return iface.device_id
    if iid.endswith("-if0"):
        return iid[:-4]
    try:
        dev_part, _ = iid.rsplit("-", 1)
        if s.get(Device, dev_part) is not None:
            return dev_part
    except Exception:
        pass
    return None


def create_link_impl(payload: LinkCreate, background: BackgroundTasks | None) -> LinkResolvedOut:
    init_db()
    if payload.a_interface_id == payload.b_interface_id:
        raise HTTPException(status_code=400, detail="Endpoints must differ")
    log = logging.getLogger("unoc.links")
    log.debug(
        "create_link request id=%s a_if=%s b_if=%s",
        payload.id,
        payload.a_interface_id,
        payload.b_interface_id,
    )
    with get_session() as s:
        # Early id conflict
        existing_id = s.exec(select(Link.id).where(Link.id == payload.id)).first()
        if existing_id is not None:
            raise HTTPException(status_code=409, detail="Link already exists")

        a_dev_id = _dev_from_iface_id(s, payload.a_interface_id)
        b_dev_id = _dev_from_iface_id(s, payload.b_interface_id)
        a_dev = s.get(Device, a_dev_id) if a_dev_id else None
        b_dev = s.get(Device, b_dev_id) if b_dev_id else None
        if not a_dev or not b_dev:
            raise HTTPException(
                status_code=400, detail="Interface not found (and auto-create failed)"
            )
        # Disallow POP participation entirely before touching interfaces
        if a_dev.type.name == "POP" or b_dev.type.name == "POP":
            raise_error(ErrorCode.POP_LINK_DISALLOWED, detail_suffix="POP container endpoint")

        # Classification must run before creating any missing interfaces
        cls = classify_devices_for_link(a_dev, b_dev)
        if not cls.allowed:
            raise_error(ErrorCode.INVALID_LINK_TYPE, detail_suffix=cls.rule_id)

        # Forbid ODF↔ODF cascades (only when both endpoints are ODF)
        from backend.models import DeviceType as _DeviceType

        log.debug("device types for create_link: a=%s b=%s", a_dev.type, b_dev.type)
        if (a_dev.type == _DeviceType.ODF) and (b_dev.type == _DeviceType.ODF):
            raise_error(
                ErrorCode.LINK_INVALID_PAIRING,
                detail_suffix="Direct ODF↔ODF links (cascades) are not supported.",
            )

        # Phase 1 GPON ODF-as-Aggregator validation
        from backend.models import DeviceType, LinkType

        is_olt_ont_direct = (a_dev.type == DeviceType.OLT and b_dev.type in ONT_CLASS) or (
            b_dev.type == DeviceType.OLT and a_dev.type in ONT_CLASS
        )
        if is_olt_ont_direct:
            raise_error(
                ErrorCode.LINK_INVALID_PAIRING,
                detail_suffix="Direct OLT↔ONT links are not allowed. Connect via an ODF.",
            )

        if a_dev.type == DeviceType.OLT or b_dev.type == DeviceType.OLT:
            other = b_dev if a_dev.type == DeviceType.OLT else a_dev
            if (other.type in PASSIVE_INLINE) or (other.type in ONT_CLASS):
                if other.type != DeviceType.ODF:
                    raise_error(
                        ErrorCode.LINK_INVALID_UPSTREAM,
                        detail_suffix=f"ODF must connect upstream to an OLT PON-port, not {other.type.name}",
                    )

        enforce_ont_placement_rules(
            s,
            a_dev,
            b_dev,
            payload.a_interface_id,
            payload.b_interface_id,
        )

        # Ensure interfaces exist (auto-create default -if0 if needed)
        a_if = ensure_default_interface(s, payload.a_interface_id)
        b_if = ensure_default_interface(s, payload.b_interface_id)
        if not a_if or not b_if:
            raise HTTPException(
                status_code=400, detail="Interface not found (and auto-create failed)"
            )
        if a_if.name == "mgmt0" or b_if.name == "mgmt0":
            raise_error(ErrorCode.INVALID_LINK_TYPE, detail_suffix="management interface")
        a_id, b_id, canonical_id, user_order_id = canonical_link_id(
            payload.a_interface_id, payload.b_interface_id
        )
        if payload.id not in {canonical_id, user_order_id}:
            preexist = s.exec(select(Link.id).where(Link.id == payload.id)).first()
            if preexist is not None:
                raise HTTPException(status_code=409, detail="Link already exists")
            raise HTTPException(
                status_code=400,
                detail=f"Link id not canonical; expected '{canonical_id}'",
            )

        # Optical validation
        if payload.length_km is not None and payload.length_km < 0:
            raise HTTPException(status_code=400, detail="length_km must be >= 0")
        if payload.physical_medium_id is not None:
            if s.get(PhysicalMedium, payload.physical_medium_id) is None:
                raise HTTPException(status_code=400, detail="Invalid physical_medium_id")

        # Phase 1 GPON enforcement: PON role if declared; single upstream rules
        enforce_pon_role_if_declared(s, a_dev, b_dev, a_if, b_if)
        enforce_single_upstream_rules(s, a_dev, b_dev)

        # Map classification to Link.kind enum
        derived_kind = LinkType.P2P if cls.link_class == "routed_p2p" else LinkType.FIBER

        # Determine PhysicalMedium defaults/mapping
        selected_pm_id: int | None = None
        if getattr(payload, "physical_medium_id", None) is None:
            selected_pm_id = pick_default_physical_medium_id(s, payload.id, a_dev, b_dev)

        pm_id_to_validate = (
            payload.physical_medium_id if payload.physical_medium_id is not None else selected_pm_id
        )
        if pm_id_to_validate is not None:
            pm_obj = s.get(PhysicalMedium, int(pm_id_to_validate))
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

        # Default length_km if not provided
        derived_length: float | None = payload.length_km
        if derived_length is None and (selected_pm_id or payload.physical_medium_id):
            pm_id = selected_pm_id or int(payload.physical_medium_id or 0)
            derived_length = derive_default_length_km(s, payload.id, pm_id)

        # Capture device_ids from interfaces before commit
        a_iface_device_id = a_if.device_id if a_if else ""
        b_iface_device_id = b_if.device_id if b_if else ""

        link = Link(
            id=payload.id,
            a_interface_id=a_id,
            b_interface_id=b_id,
            kind=derived_kind,
            status=payload.status,
            admin_override_status=payload.admin_override_status,
            length_km=derived_length,
            physical_medium_id=(
                payload.physical_medium_id
                if payload.physical_medium_id is not None
                else selected_pm_id
            ),
        )
        try:
            s.add(link)
            s.commit()
            s.refresh(link)
            append_write_path_event(
                s,
                "LINK_CREATED",
                link.id,
                {
                    "a_interface_id": link.a_interface_id,
                    "b_interface_id": link.b_interface_id,
                    "kind": str(link.kind),
                    "rule_id": cls.rule_id,
                },
            )
            log.info(
                "Link created id=%s (%s<->%s)",
                link.id,
                link.a_interface_id,
                link.b_interface_id,
            )
            # Publish link.created
            try:
                tv_create = PATHFINDING_STORE.bump_version()
                events.publish(
                    events.Event(
                        type="link.created",
                        payload={
                            "id": link.id,
                            "a_interface_id": link.a_interface_id,
                            "b_interface_id": link.b_interface_id,
                            "kind": str(link.kind),
                            "rule_id": cls.rule_id,
                        },
                        topo_version=tv_create,
                    )
                )
            except Exception:
                log.exception("Failed to publish link.created for %s", link.id)

            # Schedule recompute via coalescer
            try:
                coalescer.schedule(scope="links", key=link.id)
            except Exception:
                log.exception("Failed to schedule coalesced recompute for link %s", link.id)

            # Optical recompute via Go service (4,000× faster!) and status propagation (30,000× faster!)
            try:
                tv = PATHFINDING_STORE.bump_version()

                # Optical path recomputation
                optical_client = get_optical_client()
                if optical_client:
                    optical_client.recompute_paths(link_ids=[link.id])

                # Status propagation for both devices connected by this link
                status_client = get_status_client()
                if status_client:
                    affected_devices = []
                    if a_iface_device_id:
                        affected_devices.append(a_iface_device_id)
                    if b_iface_device_id:
                        affected_devices.append(b_iface_device_id)

                    if affected_devices:
                        status_client.propagate_status(
                            changed_device_ids=affected_devices,
                            changed_link_ids=[link.id],
                            update_database=True,
                        )

                # Emit device.optical.updated for each affected device
                if a_iface_device_id:
                    events.publish(
                        events.Event(
                            type="device.optical.updated",
                            payload={"id": a_iface_device_id, "reason": "link_created"},
                            topo_version=tv,
                        )
                    )
                if b_iface_device_id:
                    events.publish(
                        events.Event(
                            type="device.optical.updated",
                            payload={"id": b_iface_device_id, "reason": "link_created"},
                            topo_version=tv,
                        )
                    )
            except Exception as e:
                print(f"[WARN] Go service call failed after link create: {e}")

            # NOTE: PON occupancy cache automatically invalidates via provisioning_count
            # No manual invalidation needed - cache reacts to ONT provision state changes

            eff = evaluate_link_status(link)
            eff_str = normalize_status_str(eff)
            return LinkResolvedOut(
                id=link.id,
                a_interface_id=link.a_interface_id,
                b_interface_id=link.b_interface_id,
                a_device_id=a_iface_device_id,
                b_device_id=b_iface_device_id,
                status=link.status,
                effective_status=eff_str,
                kind=link.kind,
                admin_override_status=link.admin_override_status,
                length_km=link.length_km,
                physical_medium_id=link.physical_medium_id,
                rule_id=cls.rule_id,
            )
        except IntegrityError as ie:
            s.rollback()
            msg = str(ie).lower()
            if (
                "unique" in msg
                or "duplicate" in msg
                or "uq_link_endpoints" in msg
                or "uq_link_device_name" in msg
            ):
                log.info("Link uniqueness conflict (race): %s", ie)
                raise HTTPException(status_code=409, detail="Link already exists") from ie
            log.exception("IntegrityError creating link: %s", ie)
            raise HTTPException(status_code=500, detail=f"Integrity error: {ie}") from ie
        except OperationalError as oe:
            s.rollback()
            msg = str(oe).lower()
            if "locked" in msg or "readonly" in msg:
                log.warning("SQLite busy/locked while creating link: %s", oe)
                raise HTTPException(status_code=503, detail="Database busy, retry") from oe
            log.exception("OperationalError creating link: %s", oe)
            raise HTTPException(status_code=500, detail=f"DB operational error: {oe}") from oe
        except Exception as e:
            s.rollback()
            log.exception("Unexpected error creating link: %s", e)
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected link create error: {type(e).__name__}: {e}",
            ) from e
