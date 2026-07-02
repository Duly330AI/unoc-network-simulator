"""Provisioning service layer.

Provides orchestration over pure constants & low-level helpers.
"""

import logging
import os
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend import events
from backend.constants import DEVICE_PARENT_POOL_MAP
from backend.errors import ErrorCode, raise_error
from backend.models import (
    VRF,
    Device,
    DeviceType,
    Interface,
    InterfaceAddress,
    InterfaceRole,
    Prefix,
    ProvisioningAction,
    ProvisioningRecord,
)
from backend.services.event_store import append_write_path_event
from backend.services.mac_allocator import next_mac
from backend.services.provisioning_dependency import dependency_ok as _dependency_ok_impl
from backend.services.provisioning_dependency import is_provisionable as _is_provisionable_impl
from backend.services.provisioning_l3_auto import auto_configure_l3_uplinks
from backend.services.seed_service import ensure_ipam_defaults

log = logging.getLogger("unoc.provision")


def is_provisionable(device_type: DeviceType) -> bool:  # shim for public API stability
    return _is_provisionable_impl(device_type)


def classify_prefix_role(device_type: DeviceType) -> str | None:  # re-export shim for stability
    from backend.services.provisioning_ipam import classify_prefix_role as _c

    return _c(device_type)


def _next_free_ip_in_prefix(session: Session, prefix: Prefix) -> tuple[str, int] | None:  # shim
    from backend.services.provisioning_ipam import next_free_ip_in_prefix as _n

    return _n(session, prefix)


def _dependency_ok(session: Session, device: Device) -> bool:  # shim for stability
    return _dependency_ok_impl(session, device)


def provision_device(session: Session, device: Device) -> Device:
    if not is_provisionable(device.type):
        raise_error(ErrorCode.INVALID_PROVISION_PATH)
    if device.provisioned:
        raise_error(ErrorCode.ALREADY_PROVISIONED)
    # Parent / container validation (enforces DEVICE_PARENT_POOL_MAP) — run early so
    # "wrong parent type" surfaces as 422 (CONTAINER_REQUIRED) before any path checks.
    parent_rule = DEVICE_PARENT_POOL_MAP.get(device.type)
    if parent_rule:
        # If a parent is required but missing, raise
        if parent_rule.get("requires_parent"):
            if not device.parent_container_id:
                raise_error(ErrorCode.CONTAINER_REQUIRED, detail_suffix="missing parent")
        # If a parent is provided (optional or required), validate its type
        if device.parent_container_id:
            parent = session.get(Device, device.parent_container_id)
            if not parent or parent.type != parent_rule.get("parent_type"):
                raise_error(
                    ErrorCode.CONTAINER_REQUIRED,
                    detail_suffix=f"expected parent {parent_rule.get('parent_type')}",
                )
    else:
        # For devices that must NOT have a parent (implicit rule): if a parent is set but the device type
        # is not listed as requiring one, we reject to avoid silent misplacement.
        if device.parent_container_id:
            raise_error(
                ErrorCode.INVALID_PROVISION_PATH,
                detail_suffix="unexpected parent",
            )
    # Explicit strict prerequisites (defensive layer in addition to _dependency_ok):
    if device.type in {DeviceType.ONT, DeviceType.BUSINESS_ONT}:
        has_olt = session.exec(select(Device).where(Device.type == DeviceType.OLT)).first()
        if not has_olt:
            # Deterministic suffix for strict prerequisite failure (Option C)
            raise_error(
                ErrorCode.INVALID_PROVISION_PATH,
                detail_suffix="missing required upstream OLT",
            )
    if device.type == DeviceType.AON_CPE:
        has_sw = session.exec(select(Device).where(Device.type == DeviceType.AON_SWITCH)).first()
        if not has_sw:
            raise_error(
                ErrorCode.INVALID_PROVISION_PATH,
                detail_suffix="missing required upstream AON_SWITCH",
            )
    # OLT upstream prerequisite at provisioning time:
    # Require at least a structural path to any router (CORE/EDGE/BACKBONE). Do NOT require L3 to an
    # anchor yet; tolerate routers lacking L3 (reason: routers_no_l3). Reject only when there is no
    # structural router path or device is not present in graph.
    if device.type == DeviceType.OLT:
        # Fast structural guard: require a direct logical adjacency to any router-class device.
        # This aligns strict path validation expectations and avoids relying on graph state during
        # mid-transaction topologies. We intentionally DO NOT perform L3/anchor diagnostics here;
        # end-to-end reachability is enforced later by status/traffic recompute.
        try:
            session.flush()  # make pending link/interface inserts visible
        except Exception:
            pass
        from backend.services.dependency_resolver_core import _collect_devices_links as _collect

        _devs, _links, _ = _collect(session)
        structural_adjacent_to_router = False
        for lr in _links:
            if lr.a_device_id == device.id:
                other_id = lr.b_device_id
            elif lr.b_device_id == device.id:
                other_id = lr.a_device_id
            else:
                continue
            other_dev = session.get(Device, other_id)
            if other_dev and other_dev.type in {
                DeviceType.CORE_ROUTER,
                DeviceType.EDGE_ROUTER,
                DeviceType.BACKBONE_GATEWAY,
            }:
                structural_adjacent_to_router = True
                break
        if not structural_adjacent_to_router:
            raise_error(ErrorCode.INVALID_PROVISION_PATH, detail_suffix="no router adjacency")
    # Bootstrap relaxation: allow access/optical segment provisioning without strict upstream L3
    # at provisioning time. Enforce end-to-end dependency later via status/traffic gating.
    # Applies to ONT/BUSINESS_ONT/AON_CPE leaves only. OLT is enforced strictly by default
    # per PROVISION_MATRIX (requires upstream core path).
    _t = device.type
    _t_name = getattr(_t, "value", str(_t))
    skip_dependency_enforcement = _t in {
        DeviceType.OLT,
        DeviceType.ONT,
        DeviceType.BUSINESS_ONT,
        DeviceType.AON_CPE,
    } or _t_name in {"ONT", "BUSINESS_ONT", "AON_CPE"}
    # Path / graph-based dependency evaluation (strict-by-default)
    if not skip_dependency_enforcement:
        if not _dependency_ok(session, device):
            raise_error(
                ErrorCode.INVALID_PROVISION_PATH, detail_suffix="upstream dependency failed"
            )
    # Ensure base IPAM defaults (VRFs/Prefixes) exist before allocation
    ensure_ipam_defaults(session)

    prefix_role = classify_prefix_role(device.type)
    ip_addr: str | None = None
    prefix_obj: Prefix | None = None
    target_vrf: VRF | None = None
    if prefix_role:
        # Pick the relevant management prefix by role label (stored in description)
        tmp_prefix = session.exec(select(Prefix).where(Prefix.description == prefix_role)).first()
        if not tmp_prefix:
            # Fallback: try by well-known CIDR if description labels weren't set
            # NOTE: These match seed_helpers/ipam.py defaults (updated for enterprise scale)
            role_to_cidr = {
                "core_mgmt": "10.252.0.0/24",
                "olt_mgmt": "10.251.0.0/24",
                "ont_mgmt": "10.250.0.0/16",  # 65k IPs for large-scale deployments
                "aon_mgmt": "10.253.0.0/24",
                "cpe_mgmt": "10.254.0.0/24",
            }
            cidr = role_to_cidr.get(prefix_role)
            if cidr:
                tmp_prefix = session.exec(select(Prefix).where(Prefix.prefix == cidr)).first()
        # If still not present (race or cold DB), seed and retry once deterministically
        if not tmp_prefix:
            try:
                ensure_ipam_defaults(session)
            except Exception:
                pass
            # Retry description-first, then CIDR
            tmp_prefix = session.exec(
                select(Prefix).where(Prefix.description == prefix_role)
            ).first()
            if not tmp_prefix:
                cidr = {
                    "core_mgmt": "10.252.0.0/24",
                    "olt_mgmt": "10.251.0.0/24",
                    "ont_mgmt": "10.250.0.0/16",  # 65k IPs
                    "aon_mgmt": "10.253.0.0/24",
                    "cpe_mgmt": "10.254.0.0/24",
                }.get(prefix_role)
                if cidr:
                    tmp_prefix = session.exec(select(Prefix).where(Prefix.prefix == cidr)).first()
        if not tmp_prefix:
            raise_error(
                ErrorCode.INVALID_PROVISION_PATH,
                detail_suffix=f"missing prefix {prefix_role}",
            )
        # narrow type and allocate from prefix
        found_prefix: Prefix = tmp_prefix  # type: ignore[assignment]
        # Resolve target VRF for VRF-level uniqueness enforcement
        target_vrf = session.get(VRF, found_prefix.vrf_id)
        next_ip_candidate = _next_free_ip_in_prefix(session, found_prefix)
        if next_ip_candidate is None:
            raise_error(ErrorCode.POOL_EXHAUSTED)
        else:
            ip_addr, auto_prefix_len = next_ip_candidate
        prefix_obj = found_prefix
    if ip_addr and prefix_obj is not None:
        iface_id = f"{device.id}-mgmt0"
        existing = session.get(Interface, iface_id)
        # Consider duplicate if any InterfaceAddress exists
        existing_addr = None
        if existing:
            existing_addr = session.exec(
                select(InterfaceAddress).where(InterfaceAddress.interface_id == iface_id)
            ).first()
        if existing and existing_addr:
            # Idempotent acceptance for CORE/EDGE routers: treat pre-existing mgmt address
            # as already allocated by operations or a previous flow. Do NOT error out; instead
            # continue and mark device as provisioned. Keep strict behavior for other device types.
            if device.type in {DeviceType.CORE_ROUTER, DeviceType.EDGE_ROUTER}:
                try:
                    # Reuse the current address context for audit/event payloads
                    ip_addr = existing_addr.ip  # type: ignore[assignment]
                    prefix_obj = session.get(Prefix, existing_addr.prefix_id) or prefix_obj
                    # Resolve VRF for audit trail if possible
                    target_vrf = (
                        session.get(VRF, prefix_obj.vrf_id)
                        if prefix_obj and prefix_obj.vrf_id
                        else None
                    )
                except Exception:
                    pass  # best effort only
            else:
                raise_error(ErrorCode.DUPLICATE_MGMT_INTERFACE)
        if not existing:
            existing = Interface(
                id=iface_id,
                device_id=device.id,
                name="mgmt0",
                role=InterfaceRole.MANAGEMENT,
                mac_address=next_mac(),
            )
            session.add(existing)
        # Create address (if none exists yet) with VRF uniqueness and simple retry-on-conflict
        has_addr = session.exec(
            select(InterfaceAddress).where(InterfaceAddress.interface_id == iface_id)
        ).first()
        if not has_addr:
            max_retries = 5
            attempt = 0
            while True:
                try:
                    # Guard: ensure IP is not taken in target VRF scope
                    if target_vrf is not None:
                        existing_ip = session.exec(
                            select(InterfaceAddress).where(
                                (InterfaceAddress.vrf_id == target_vrf.id)
                                & (InterfaceAddress.ip == ip_addr)
                            )
                        ).first()
                        if existing_ip:
                            # Find next free within prefix
                            nxt = _next_free_ip_in_prefix(session, prefix_obj)
                            if nxt is None:
                                raise_error(ErrorCode.POOL_EXHAUSTED)
                            assert nxt is not None
                            ip_addr, auto_prefix_len = nxt
                    session.add(
                        InterfaceAddress(
                            interface_id=iface_id,
                            ip=ip_addr,
                            prefix_len=auto_prefix_len,
                            prefix_id=prefix_obj.id,
                            vrf_id=target_vrf.id if target_vrf is not None else None,
                        )
                    )
                    session.flush()  # try persisting early to surface UNIQUE conflicts
                    break
                except IntegrityError:
                    session.rollback()
                    attempt += 1
                    # Pick next candidate and retry
                    nxt = _next_free_ip_in_prefix(session, prefix_obj)
                    if nxt is None:
                        raise_error(ErrorCode.POOL_EXHAUSTED)
                    assert nxt is not None
                    ip_addr, auto_prefix_len = nxt
                    if attempt >= max_retries:
                        # After several conflicts, treat as exhaustion in practice
                        raise_error(ErrorCode.POOL_EXHAUSTED)
    # Defaults (signal placeholders)
    if device.type == DeviceType.OLT and device.tx_power_dbm is None:
        device.tx_power_dbm = 5.0
    if (
        device.type in {DeviceType.ONT, DeviceType.BUSINESS_ONT}
        and device.sensitivity_min_dbm is None
    ):
        device.sensitivity_min_dbm = -30.0
    device.provisioned = True
    session.add(device)
    log.info("Provisioned device id=%s type=%s ip=%s", device.id, device.type, ip_addr)

    # Audit: record provisioning action (TASK-514)
    if ip_addr and prefix_obj is not None:
        ts = datetime.now(UTC).isoformat()
        rec = ProvisioningRecord(
            ts=ts,
            action=ProvisioningAction.ASSIGN_MGMT_IP,
            device_id=device.id,
            interface_id=f"{device.id}-mgmt0",
            ip=ip_addr,
            vrf_id=target_vrf.id if target_vrf is not None else None,
            prefix_id=prefix_obj.id,
            actor=os.getenv("UNOC_ACTOR", "system"),
            correlation_id=os.getenv("UNOC_CORRELATION_ID", None),
        )
        session.add(rec)

    # Note: Event emission moved to API/background layer to avoid duplicates

    # Proceed with optical hooks; status change events are emitted by the central
    # recompute utility in the API layer when applicable.
    # Optical recompute placeholder hook (TASK-112): trigger for optical relevant devices
    if device.type in {
        DeviceType.OLT,
        DeviceType.ONT,
        DeviceType.BUSINESS_ONT,
        DeviceType.ODF,
        DeviceType.NVT,
        DeviceType.SPLITTER,
        DeviceType.HOP,
    }:
        # Optical recompute handled by background workflow after API commit
        pass
    # Ensure persistence of provisioning changes even if status didn't change
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    append_write_path_event(
        session,
        "PROVISIONING_UPDATED",
        device.id,
        {"device_type": device.type.value, "provisioned": True, "ip": ip_addr},
    )
    # Emit provisioned event once from service layer so both direct and API paths see it
    try:
        from backend.services.pathfinding import PATHFINDING_STORE as _pf

        tv_now = _pf.bump_version()
        events.publish(
            events.Event(
                type="device.provisioned",
                payload={
                    "id": device.id,
                    "type": device.type.value,
                    "ip": ip_addr,
                },
                topo_version=tv_now,
            )
        )
    except Exception:
        # best-effort; do not fail provisioning on event errors
        pass
    # Intelligent L3 auto-configuration for router uplinks (idempotent).
    # Always-on: auto-configure L3 adjacencies after the initial provisioning commit
    # to minimize chances of conflicting with mgmt IP allocation retry logic above.
    try:
        auto_configure_l3_uplinks(session, device)
    except Exception:
        # Never fail provisioning due to auto L3 helper; leave for manual remediation.
        pass
    return device
