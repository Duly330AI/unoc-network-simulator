"""Core mutation helpers for devices (create/update).

This module contains ConflictError, UnprocessableError, and the
create_device_impl/update_device_impl functions. Delete logic is in
devices_helpers_delete.py. Public API is re-exported via
devices_helpers_mutation.py.
"""

from __future__ import annotations

from sqlmodel import Session, select

from backend import events
from backend.api.schemas import DeviceCreate, DeviceOut, DeviceUpdate
from backend.clients.go_services.optical_client import get_optical_client
from backend.clients.go_services.status_client import get_status_client
from backend.models import (
    BridgeDomain,
    Device,
    DeviceType,
    HardwareModel,
    Interface,
    InterfaceRole,
    PortProfile,
    Tariff,
)
from backend.services.mac_allocator import next_mac
from backend.services.event_store import append_domain_event
from backend.services.event_store_runtime import projection_write
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.seed_service import allocate_backbone_mgmt, ensure_default_tariffs
from backend.services.splitter_service import DEFAULT_SPLIT_RATIO, ensure_default_ports_for_splitter
from backend.utils import validate_parent_child


class ConflictError(Exception):
    pass


class UnprocessableError(Exception):
    pass


def _append_pending_port_events(s: Session) -> None:
    """Append PORT_CONNECTED for interfaces pending in this transaction (event-first)."""
    for obj in list(s.new):
        if isinstance(obj, Interface):
            append_domain_event(
                s,
                "PORT_CONNECTED",
                obj.id,
                {"device_id": obj.device_id, "name": obj.name},
            )


@projection_write
def create_device_impl(s: Session, payload: DeviceCreate) -> DeviceOut:
    # Ensure default tariffs exist for intelligent assignment (TASK-407)
    try:
        ensure_default_tariffs(s)
    except Exception:
        # Non-fatal: device creation should not fail if seeding cannot run
        pass
    if s.get(Device, payload.id):
        raise ConflictError("Device ID already exists")

    # Single-backbone enforcement & optional mgmt IP allocation (TASK-052 extension)
    if payload.type == DeviceType.BACKBONE_GATEWAY:
        from os import getenv

        enforce_single = getenv("ENSURE_SINGLE_BACKBONE_GATEWAY", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if enforce_single:
            existing_bb = s.exec(
                select(Device).where(Device.type == DeviceType.BACKBONE_GATEWAY)
            ).first()
            if existing_bb:
                raise ConflictError("Backbone gateway already exists (single mode)")

    ok, err = validate_parent_child(s, payload.type, payload.parent_container_id)
    if not ok:
        raise UnprocessableError(err or "INVALID_PARENT")

    # Validate hardware_model_id if provided
    if payload.hardware_model_id is not None:
        hm = s.get(HardwareModel, payload.hardware_model_id)
        if not hm:
            raise UnprocessableError("INVALID_HARDWARE_MODEL")
        # basic type compatibility check
        if hm.device_type != payload.type:
            raise UnprocessableError("HARDWARE_TYPE_MISMATCH")
    else:
        # Optional: auto-assign default hardware model by type when enabled.
        # Read via Settings so both process env and a root .env file work.
        from backend.core.config import get_settings

        auto_assign = get_settings().auto_assign_default_hardware
        if auto_assign:
            rows = s.exec(
                select(HardwareModel)
                .where(HardwareModel.device_type == payload.type)
                .order_by(HardwareModel.vendor, HardwareModel.model, HardwareModel.version)
            ).all()
            chosen = None
            for r in rows:
                if getattr(r, "meta_source", None) == "default":
                    chosen = r
                    break
            if not chosen and rows:
                chosen = rows[0]
            if chosen and chosen.id is not None:
                payload.hardware_model_id = int(chosen.id)

    d = Device(
        id=payload.id,
        name=payload.name,
        type=payload.type,
        status=payload.status,
        parent_container_id=payload.parent_container_id,
        hardware_model_id=payload.hardware_model_id,
    )
    # If a hardware model is assigned and device is passive, propagate default insertion loss
    try:
        if d.hardware_model_id is not None and d.type in {
            DeviceType.SPLITTER,
            DeviceType.HOP,
            DeviceType.NVT,
            DeviceType.ODF,
        }:
            hm = s.get(HardwareModel, d.hardware_model_id)
            if hm and getattr(hm, "insertion_loss_db", None) is not None:
                d.insertion_loss_db = hm.insertion_loss_db  # type: ignore[assignment]
    except Exception:
        # Non-fatal; leave as None if catalog lookup fails
        pass
    append_domain_event(
        s,
        "DEVICE_CREATED",
        d.id,
        {"device_type": d.type.value, "name": d.name, "status": str(d.status)},
    )
    s.add(d)
    s.commit()
    PATHFINDING_STORE.bump_version()
    s.refresh(d)

    # TASK-407: Assign default tariff for certain leaf device types if not set by update
    try:
        if d.type in {DeviceType.ONT, DeviceType.BUSINESS_ONT, DeviceType.AON_CPE}:
            if d.tariff_id is None:
                # Determine required technology
                if d.type == DeviceType.AON_CPE:
                    desired_tech = Tariff.TariffTechnology.AON  # type: ignore[attr-defined]
                else:
                    desired_tech = Tariff.TariffTechnology.GPON  # type: ignore[attr-defined]
                rows = s.exec(
                    select(Tariff).where(Tariff.technology == desired_tech).order_by(Tariff.name)
                ).all()
                if rows:
                    d.tariff_id = rows[0].id
                    s.add(d)
                    s.commit()
                    s.refresh(d)
    except Exception:
        pass

    # L2: auto-create default bridge-domain for switch-like devices (TASK-533)
    if d.type in {DeviceType.AON_SWITCH, DeviceType.EDGE_ROUTER}:
        bd = s.exec(
            select(BridgeDomain).where(
                (BridgeDomain.device_id == d.id) & (BridgeDomain.name == "default")
            )
        ).first()
        if not bd:
            bd = BridgeDomain(name="default", device_id=d.id)
            s.add(bd)
            s.commit()
            s.refresh(bd)

    # Auto-provision interfaces from catalog when hardware_model_id supplied
    if d.hardware_model_id is not None:
        profiles = s.exec(
            select(PortProfile).where(PortProfile.hardware_model_id == d.hardware_model_id)
        ).all()
        created_any = False
        for p in profiles:
            count = max(0, int(p.count or 0))
            base = (p.name or "port").strip() or "port"
            if count <= 0:
                continue
            for idx in range(1, count + 1):
                if count == 1 and base in {"mgmt0", "if0", "mgmt", "uplink"}:
                    if_name = base if base.endswith("0") else f"{base}0"
                else:
                    if_name = f"{base}{idx}"
                iface_id = f"{d.id}-{if_name}"
                if not s.get(Interface, iface_id):
                    s.add(
                        Interface(
                            id=iface_id,
                            device_id=d.id,
                            name=if_name,
                            role=(
                                InterfaceRole.MANAGEMENT
                                if (p.role or "").lower() == "management"
                                else None
                            ),
                            capacity=(
                                int(p.speed_gbps * 1000) if p.speed_gbps is not None else None
                            ),
                            profile_name=base,
                            port_role=getattr(p, "port_role", None),
                            mac_address=next_mac(),
                        )
                    )
                    created_any = True
        if created_any:
            _append_pending_port_events(s)
            s.commit()
        # assign default bridge-domain if exists and ports have none
        if d.type in {DeviceType.AON_SWITCH, DeviceType.EDGE_ROUTER}:
            bd = s.exec(
                select(BridgeDomain).where(
                    (BridgeDomain.device_id == d.id) & (BridgeDomain.name == "default")
                )
            ).first()
            if bd:
                ifaces = s.exec(select(Interface).where(Interface.device_id == d.id)).all()
                updated = False
                for i in ifaces:
                    if i.bridge_domain_id is None:
                        i.bridge_domain_id = bd.id
                        s.add(i)
                        updated = True
                if updated:
                    s.commit()
    else:
        # fallback: if no hardware model, create default interfaces
        if d.type == DeviceType.SPLITTER:
            ensure_default_ports_for_splitter(s, d, DEFAULT_SPLIT_RATIO)
            _append_pending_port_events(s)
            s.commit()
        else:
            iface_id = f"{d.id}-if0"
            if not s.get(Interface, iface_id):
                s.add(Interface(id=iface_id, device_id=d.id, name="if0", mac_address=next_mac()))
                _append_pending_port_events(s)
                s.commit()

    # Optional backbone mgmt IP allocation (prefix-based)
    if d.type == DeviceType.BACKBONE_GATEWAY:
        from os import getenv

        allow_mgmt = getenv("ALLOW_BACKBONE_MGMT_IP", "false").lower() in {"1", "true", "yes", "on"}
        if allow_mgmt:
            allocate_backbone_mgmt(s, d)
            _append_pending_port_events(s)
            s.commit()

    # Trigger status propagation via Go service (30,000× faster than Python!)
    try:
        status_client = get_status_client()
        if status_client:
            # Device creation might affect downstream status (e.g., new backbone gateway)
            status_client.propagate_status(
                changed_device_ids=[d.id], changed_link_ids=[], update_database=True
            )
    except Exception as e:
        # Non-fatal: device is created successfully, status propagation can retry later
        print(f"[WARN] Status propagation failed after device create: {e}")

    # NOTE: PON occupancy cache automatically invalidates via provisioning_count in cache key
    # No manual invalidation needed - cache reacts to ONT provision state changes


    return DeviceOut.from_model(d)


@projection_write
def update_device_impl(s: Session, device_id: str, payload: DeviceUpdate) -> DeviceOut:
    d = s.get(Device, device_id)
    if not d:
        raise LookupError("Not found")
    data = payload.model_dump(exclude_unset=True)

    # validate hardware_model compatibility
    if "hardware_model_id" in data:
        new_hm_id = data.get("hardware_model_id")
        if new_hm_id is not None:
            hm = s.get(HardwareModel, new_hm_id)
            if not hm:
                raise UnprocessableError("INVALID_HARDWARE_MODEL")
            if hm.device_type != d.type:
                raise UnprocessableError("HARDWARE_TYPE_MISMATCH")

    # validate parent/child rules
    if "parent_container_id" in data:
        new_parent = data.get("parent_container_id")
        ok, err = validate_parent_child(s, d.type, new_parent)
        if not ok:
            raise UnprocessableError(str(err) if err else "INVALID_PARENT")

    # Tariff technology enforcement (TASK-401)
    if "tariff_id" in data:
        new_tid = data.get("tariff_id")
        if new_tid is not None:
            t = s.get(Tariff, int(new_tid))
            if not t:
                raise UnprocessableError("TARIFF_NOT_FOUND")
            required = None
            if d.type in {DeviceType.ONT, DeviceType.BUSINESS_ONT}:
                required = Tariff.TariffTechnology.GPON  # type: ignore[attr-defined]
            elif d.type == DeviceType.AON_CPE:
                required = Tariff.TariffTechnology.AON  # type: ignore[attr-defined]
            if required is not None and t.technology is not None and t.technology != required:
                raise UnprocessableError("TARIFF_TECH_MISMATCH")

    before_status = d.status
    before_override = getattr(d, "admin_override_status", None)
    before_tx = getattr(d, "tx_power_dbm", None)
    before_rx = getattr(d, "sensitivity_min_dbm", None)
    before_ins = getattr(d, "insertion_loss_db", None)

    # Normalize slot handling
    if "parent_container_id" in data and data.get("parent_container_id") is None:
        data["slot_id"] = None
    if (
        "slot_id" in data
        and data.get("slot_id") is not None
        and data.get("parent_container_id") is None
        and getattr(d, "parent_container_id", None) is None
    ):
        data["slot_id"] = None

    append_domain_event(
        s,
        "DEVICE_UPDATED",
        d.id,
        {"device_type": d.type.value, "changed_fields": sorted(data.keys())},
    )
    for k, v in data.items():
        setattr(d, k, v)
    s.add(d)
    s.commit()
    tv = PATHFINDING_STORE.bump_version()
    s.refresh(d)

    # Auto-create interfaces when hardware model is newly assigned or changed
    if "hardware_model_id" in data and d.hardware_model_id is not None:
        if d.type in {DeviceType.AON_SWITCH, DeviceType.EDGE_ROUTER}:
            bd = s.exec(
                select(BridgeDomain).where(
                    (BridgeDomain.device_id == d.id) & (BridgeDomain.name == "default")
                )
            ).first()
            if not bd:
                bd = BridgeDomain(name="default", device_id=d.id)
                s.add(bd)
                s.commit()
                s.refresh(bd)
        profiles = s.exec(
            select(PortProfile).where(PortProfile.hardware_model_id == d.hardware_model_id)
        ).all()
        created_any = False
        for p in profiles:
            count = max(0, int(p.count or 0))
            base = (p.name or "port").strip() or "port"
            if count <= 0:
                continue
            for idx in range(1, count + 1):
                if count == 1 and base in {"mgmt0", "if0", "mgmt", "uplink"}:
                    if_name = base if base.endswith("0") else f"{base}0"
                else:
                    if_name = f"{base}{idx}"
                iface_id = f"{d.id}-{if_name}"
                if not s.get(Interface, iface_id):
                    s.add(
                        Interface(
                            id=iface_id,
                            device_id=d.id,
                            name=if_name,
                            role=(
                                InterfaceRole.MANAGEMENT
                                if (p.role or "").lower() == "management"
                                else None
                            ),
                            capacity=(
                                int(p.speed_gbps * 1000) if p.speed_gbps is not None else None
                            ),
                            profile_name=base,
                            port_role=getattr(p, "port_role", None),
                            mac_address=next_mac(),
                        )
                    )
                    created_any = True
        if created_any:
            _append_pending_port_events(s)
            s.commit()
        if d.type in {DeviceType.AON_SWITCH, DeviceType.EDGE_ROUTER}:
            bd = s.exec(
                select(BridgeDomain).where(
                    (BridgeDomain.device_id == d.id) & (BridgeDomain.name == "default")
                )
            ).first()
            if bd:
                ifaces = s.exec(select(Interface).where(Interface.device_id == d.id)).all()
                updated = False
                for i in ifaces:
                    if i.bridge_domain_id is None:
                        i.bridge_domain_id = bd.id
                        s.add(i)
                        updated = True
                if updated:
                    s.commit()

    after = DeviceOut.from_model(d)

    # Trigger status propagation via Go service if status changed (30,000× faster!)
    if before_status != after.status or before_override != after.admin_override_status:
        _evt = events.Event(
            type="device.status.changed",
            payload={
                "id": d.id,
                "status": str(after.status),
                "effective_status": str(after.status),
                "admin_override_status": (
                    str(after.admin_override_status) if after.admin_override_status else None
                ),
            },
            topo_version=tv,
        )
        events.publish(_evt)

        # Propagate status changes via Go service
        try:
            status_client = get_status_client()
            if status_client:
                status_client.propagate_status(
                    changed_device_ids=[d.id], changed_link_ids=[], update_database=True
                )
        except Exception as e:
            print(f"[WARN] Status propagation failed after device update: {e}")

    # Trigger optical recompute if optical attrs changed (Go service: 4,000× faster!)
    after_tx = getattr(d, "tx_power_dbm", None)
    after_rx = getattr(d, "sensitivity_min_dbm", None)
    after_ins = getattr(d, "insertion_loss_db", None)
    if (before_tx != after_tx) or (before_rx != after_rx) or (before_ins != after_ins):
        try:
            optical_client = get_optical_client()
            if optical_client:
                optical_client.recompute_paths(device_ids=[d.id])
        except Exception as e:  # pragma: no cover
            print(f"[WARN] Optical recompute failed after device update: {e}")

    # NOTE: PON occupancy cache automatically invalidates via provisioning_count in cache key
    # No manual invalidation needed - cache reacts to ONT provision state changes


    return after
