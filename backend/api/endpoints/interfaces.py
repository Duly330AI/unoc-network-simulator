import ipaddress
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend.db import get_session, init_db
from backend.models import Device, Interface, InterfaceAddress, InterfaceRole, PortRole, Prefix
from backend.services import recompute_coalescer
from backend.services.event_store import append_write_path_event
from backend.services.mac_allocator import next_mac
from backend.services.pathfinding import PATHFINDING_STORE

router = APIRouter(tags=["interfaces"], prefix="/devices/{device_id}/interfaces")
addr_router = APIRouter(tags=["interfaces"], prefix="/interfaces/{interface_id}/addresses")


@router.get("")
def list_interfaces(device_id: str):
    init_db()
    with get_session() as s:
        d = s.get(Device, device_id)
        if not d:
            raise HTTPException(status_code=404, detail="Device not found")
        rows = s.exec(select(Interface).where(Interface.device_id == device_id)).all()
        return [
            {
                "id": i.id,
                "device_id": i.device_id,
                "name": i.name,
                "mac_address": i.mac_address,
                "role": str(i.role) if i.role else None,
                "admin_status": str(getattr(i, "admin_status", "up")),
                # interface logical status removed; use admin_status
                "capacity": i.capacity,
            }
            for i in rows
        ]


@router.post("", status_code=201)
def create_interface(device_id: str, payload: dict):
    init_db()
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    role = payload.get("role")
    with get_session() as s:
        d = s.get(Device, device_id)
        if not d:
            raise HTTPException(status_code=404, detail="Device not found")
        iface_id = f"{device_id}-{name}"
        if s.get(Interface, iface_id):
            raise HTTPException(status_code=409, detail="Interface already exists")
        # Optional port_role support to mark semantics (e.g., PON on OLT)
        port_role_raw = payload.get("port_role")
        port_role: PortRole | None = None
        if port_role_raw is not None:
            try:
                port_role = PortRole(port_role_raw)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="invalid port_role") from exc

        i = Interface(
            id=iface_id,
            device_id=device_id,
            name=name,
            mac_address=next_mac(),
        )
        if role:
            try:
                i.role = InterfaceRole(role)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="invalid role") from exc
        if port_role is not None:
            i.port_role = port_role
        s.add(i)
        try:
            s.commit()
        except IntegrityError as exc:
            # Handle unique violations (device_id+name or mac uniqueness)
            s.rollback()
            raise HTTPException(status_code=409, detail="INTERFACE_CONFLICT") from exc
        s.refresh(i)
        append_write_path_event(
            s,
            "PORT_CONNECTED",
            i.id,
            {"device_id": i.device_id, "name": i.name, "port_role": str(i.port_role) if i.port_role else None},
        )
        return {
            "id": i.id,
            "device_id": i.device_id,
            "name": i.name,
            "mac_address": i.mac_address,
            "role": str(i.role) if i.role else None,
            "admin_status": str(getattr(i, "admin_status", "up")),
            # interface logical status removed; use admin_status
            "capacity": i.capacity,
        }


@addr_router.get("")
def list_interface_addresses(interface_id: str):
    init_db()
    with get_session() as s:
        iface = s.get(Interface, interface_id)
        if not iface:
            raise HTTPException(status_code=404, detail="Interface not found")
        rows = s.exec(
            select(InterfaceAddress).where(InterfaceAddress.interface_id == interface_id)
        ).all()
        # Resolve prefix strings in bulk
        prefix_ids = {cast(int, a.prefix_id) for a in rows if a.prefix_id is not None}
        prefix_map: dict[int, str] = {}
        if prefix_ids:
            cond = cast(Any, Prefix.id).in_(list(prefix_ids))
            pref_rows = s.exec(select(Prefix).where(cond)).all()
            for p in pref_rows:
                if p.id is not None:
                    prefix_map[int(p.id)] = p.prefix
        return [
            {
                "id": a.id,
                "interface_id": a.interface_id,
                "ip": a.ip,
                "prefix_len": a.prefix_len,
                "prefix_id": a.prefix_id,
                "prefix_string": (
                    prefix_map.get(cast(int, a.prefix_id)) if a.prefix_id is not None else None
                ),
            }
            for a in rows
        ]


@addr_router.post("", status_code=201)
def create_interface_address(interface_id: str, payload: dict):
    init_db()
    ip = payload.get("ip")
    prefix_len = payload.get("prefix_len")
    prefix_id = payload.get("prefix_id")
    if not ip and prefix_len is None and prefix_id is None:
        raise HTTPException(status_code=422, detail="provide either ip/prefix_len or prefix_id")
    # Validate IPv4
    ip_obj = None
    pl = None
    if ip:
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.version != 4:
                raise ValueError("not ipv4")
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid ip") from exc
    if prefix_len is not None:
        try:
            pl = int(prefix_len)
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=422, detail="invalid prefix_len") from exc
        if not (1 <= pl <= 32):
            raise HTTPException(status_code=422, detail="invalid prefix_len")
    with get_session() as s:
        iface = s.get(Interface, interface_id)
        if not iface:
            raise HTTPException(status_code=404, detail="Interface not found")
        # If prefix_id is provided, ensure the given ip (if any) fits inside; or if ip not provided, allocate next IP from prefix (simple first-fit for now)
        pref_obj = None
        if prefix_id is not None:
            pref_obj = s.get(Prefix, int(prefix_id))
            if not pref_obj:
                raise HTTPException(status_code=404, detail="Prefix not found")
            # Validate/derive ip + prefix_len from prefix
            net = ipaddress.ip_network(pref_obj.prefix)
            if ip_obj is None:
                # allocate first available host not used in this prefix
                used = {
                    ia.ip
                    for ia in s.exec(
                        select(InterfaceAddress).where(InterfaceAddress.prefix_id == pref_obj.id)
                    ).all()
                }
                chosen = None
                for host in net.hosts():
                    if str(host) not in used:
                        chosen = str(host)
                        break
                if not chosen:
                    raise HTTPException(status_code=409, detail="Prefix exhausted")
                ip = chosen
                ip_obj = ipaddress.ip_address(ip)
            else:
                if ip_obj not in ipaddress.ip_network(pref_obj.prefix):
                    raise HTTPException(status_code=422, detail="ip not contained in prefix")
                # If specific IP provided within prefix, ensure it's not already used in this prefix
                dup = s.exec(
                    select(InterfaceAddress).where(
                        (InterfaceAddress.prefix_id == pref_obj.id)
                        & (InterfaceAddress.ip == str(ip_obj))
                    )
                ).first()
                if dup:
                    raise HTTPException(status_code=409, detail="duplicate ip in prefix")
            pl = net.prefixlen
        # Fall-through: ip and pl must be ready here
        if ip_obj is None or pl is None:
            raise HTTPException(status_code=422, detail="ip/prefix_len resolution failed")
        a = InterfaceAddress(
            interface_id=interface_id,
            ip=str(ip_obj),
            prefix_len=pl,
            prefix_id=(pref_obj.id if pref_obj else None),
        )
        s.add(a)
        try:
            s.commit()
        except IntegrityError as exc:
            # covers VRF/prefix unique constraints collisions
            s.rollback()
            raise HTTPException(status_code=409, detail="DUPLICATE_IP") from exc
        s.refresh(a)
        append_write_path_event(
            s,
            "PROVISIONING_UPDATED",
            interface_id,
            {"address_id": a.id, "ip": a.ip, "prefix_len": a.prefix_len},
        )
        # IP address mutations can influence reachability; bump and schedule recompute
        PATHFINDING_STORE.bump_version()
        recompute_coalescer.schedule(scope="addresses", key=interface_id)
        return {
            "id": a.id,
            "interface_id": a.interface_id,
            "ip": a.ip,
            "prefix_len": a.prefix_len,
            "prefix_id": a.prefix_id,
        }


@addr_router.delete("/{address_id}", status_code=204)
def delete_interface_address(interface_id: str, address_id: int):
    init_db()
    with get_session() as s:
        iface = s.get(Interface, interface_id)
        if not iface:
            raise HTTPException(status_code=404, detail="Interface not found")
        a = s.get(InterfaceAddress, address_id)
        if not a or a.interface_id != interface_id:
            raise HTTPException(status_code=404, detail="Address not found")
        s.delete(a)
        s.commit()
        append_write_path_event(
            s,
            "PROVISIONING_UPDATED",
            interface_id,
            {"address_id": address_id, "action": "address_deleted"},
        )
        # Invalidate on address removal as well
        PATHFINDING_STORE.bump_version()
        recompute_coalescer.schedule(scope="addresses", key=interface_id)
        return None


__all__ = ["router", "addr_router"]
