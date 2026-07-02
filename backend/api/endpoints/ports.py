from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.api.schemas import InterfaceSummaryOut
from backend.clients.go_services.optical_client import OpticalClient
from backend.clients.port_summary_client import PortSummaryClient, get_port_summary_client
from backend.core.limits import limiter
from backend.db import get_async_session, get_session
from backend.models import Device, DeviceType, Interface, Link, PortProfile, PortRole
from backend.services.optical_path_resolver import resolve_optical_path
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_device_status, evaluate_link_status
from backend.services.subscriber_model import (
    aon_access_port_state_for,
    aon_access_occupancy_for,
    pon_port_state_for,
    pon_occupancy_for,
    resolve_subscriber_model,
)

router = APIRouter(tags=["ports"], prefix="/ports")

# Optical Go Service client (singleton)
_optical_client: OpticalClient | None = None


def get_optical_client() -> OpticalClient:
    global _optical_client
    if _optical_client is None:
        _optical_client = OpticalClient()
    return _optical_client


# Port Summary Go Service client (singleton)
_port_summary_client: PortSummaryClient | None | bool = None


def get_port_summary_go_client() -> PortSummaryClient | None:
    """Get Port Summary Go Service client (with fallback to None if unavailable)."""
    global _port_summary_client
    if _port_summary_client is None:
        try:
            _port_summary_client = get_port_summary_client()
        except Exception:
            # Service unavailable - will fall back to Python
            _port_summary_client = False  # Sentinel to avoid retrying
    return _port_summary_client if isinstance(_port_summary_client, PortSummaryClient) else None


# Guardrail for bulk endpoint
MAX_BULK_IDS = 100

# LIVE CACHE: Reduced TTL + Provisioning-Sensitive for real-time cockpit updates
# Cache invalidates on BOTH topology changes AND provisioning events
_PORTS_CACHE_TTL_SEC = 1.0  # 1 second (was 5s, too long for live updates)
_ports_summary_cache: dict[tuple[int, str], tuple[float, list[InterfaceSummaryOut]]] = {}
_ports_summary_locks: dict[tuple[int, str], asyncio.Lock] = {}

# OLT PON occupancy cache: No cache for small topologies, direct query is fast enough
# Cache key includes provisioning_count to auto-invalidate on ONT provision/deprovision
_olt_pon_occ_cache: dict[tuple[int, str, int], dict[str, int]] = {}
_olt_pon_occ_locks: dict[tuple[int, str, int], asyncio.Lock] = {}


def _resolve_subscriber_model_sync() -> dict:
    with get_session() as sync_session:
        return resolve_subscriber_model(sync_session)


async def _resolve_subscriber_model_async() -> dict:
    return await asyncio.to_thread(_resolve_subscriber_model_sync)


def _with_canonical_subscribers(
    device_id: str, rows: list[InterfaceSummaryOut] | list[dict], model: dict
) -> list:
    pon_occ = pon_occupancy_for(model, device_id)
    aon_occ = aon_access_occupancy_for(model, device_id)
    pon_ports = pon_port_state_for(model, device_id)
    aon_ports = aon_access_port_state_for(model, device_id)
    patched: list = []
    for row in rows:
        if isinstance(row, dict):
            item = dict(row)
            iface_id = str(item.get("id") or "")
            if iface_id in pon_occ:
                item["occupancy"] = pon_occ[iface_id]
                state = pon_ports.get(iface_id, {})
                item["provisioned_onts_count"] = state.get("provisioned_onts_count", pon_occ[iface_id])
                item["max_capacity"] = state.get("max_capacity", item.get("capacity"))
                item["utilization"] = state.get("utilization")
            if iface_id in aon_occ:
                item["port_role"] = "ACCESS"
                item["occupancy"] = aon_occ[iface_id]
                state = aon_ports.get(iface_id, {})
                item["provisioned_cpes_count"] = state.get("provisioned_cpes_count", aon_occ[iface_id])
                item["max_capacity"] = state.get("max_capacity", 1)
                item["capacity"] = state.get("max_capacity", item.get("capacity"))
                item["utilization"] = state.get("utilization")
            patched.append(item)
            continue

        iface_id = str(row.id or "")
        if iface_id in pon_occ:
            row.occupancy = pon_occ[iface_id]
            state = pon_ports.get(iface_id, {})
            row.provisioned_onts_count = int(state.get("provisioned_onts_count", pon_occ[iface_id]))
            row.max_capacity = int(state.get("max_capacity", row.capacity or 0)) or None
            row.utilization = state.get("utilization")
        if iface_id in aon_occ:
            row.port_role = PortRole.ACCESS
            row.occupancy = aon_occ[iface_id]
            state = aon_ports.get(iface_id, {})
            row.provisioned_cpes_count = int(state.get("provisioned_cpes_count", aon_occ[iface_id]))
            row.max_capacity = int(state.get("max_capacity", 1))
            row.capacity = int(state.get("max_capacity", row.capacity or 1))
            row.utilization = state.get("utilization")
        patched.append(row)
    return patched


async def _get_olt_pon_occupancy(
    s: AsyncSession,
    olt: Device,
    ifaces: Sequence[Interface],
    links: Sequence[Link],
    tv: int,
) -> dict[str, int]:
    """Compute PON occupancy for an OLT by counting provisioned ONTs per PON port.

    SIMPLE LOGIC (like ACCESS ports):
    1. Get all provisioned ONTs
    2. For each ONT: Find which PON port it connects to (via optical path)
    3. Count ONTs per PON port

    Cache invalidates automatically via provisioning_count in cache key.
    """
    # Query provisioned ONT count FIRST for cache key
    res_prov_count = await s.exec(
        select(Device).where(
            ((Device.type == DeviceType.ONT) | (Device.type == DeviceType.BUSINESS_ONT))
            & (Device.provisioned == True)  # noqa: E712
        )
    )
    provisioned_onts = res_prov_count.all()
    provisioning_count = len(provisioned_onts)

    # Cache key includes provisioning count for live updates
    cache_key = (tv, olt.id, provisioning_count)
    cached = _olt_pon_occ_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    lock = _olt_pon_occ_locks.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _olt_pon_occ_locks[cache_key] = lock
    async with lock:
        # Double-check after acquiring the lock
        cached = _olt_pon_occ_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        # Build interface maps
        ifmap = {i.id: i for i in ifaces}
        iface_ids = {i.id for i in ifaces}
        pon_ifaces = [i for i in ifaces if getattr(i, "port_role", None) == PortRole.PON]

        # Early exit: no PON interfaces
        if not pon_ifaces:
            _olt_pon_occ_cache[cache_key] = {}
            return {}

        # Build links_by_if map (same as ACCESS port logic)
        links_by_if: dict[str, list[Link]] = {iid: [] for iid in iface_ids}
        for ln in links:
            if ln.a_interface_id in links_by_if:
                links_by_if[ln.a_interface_id].append(ln)
            if ln.b_interface_id in links_by_if:
                links_by_if[ln.b_interface_id].append(ln)

        # Precompute neighbor device IDs per interface
        neigh_by_if: dict[str, set[str]] = {i.id: set() for i in ifaces}
        counterpart_ids: set[str] = set()
        for ln in links:
            if ln.a_interface_id and ln.a_interface_id not in iface_ids:
                counterpart_ids.add(ln.a_interface_id)
            if ln.b_interface_id and ln.b_interface_id not in iface_ids:
                counterpart_ids.add(ln.b_interface_id)
        counterpart_dev_by_if: dict[str, str] = {}
        if counterpart_ids:
            res_counterparts = await s.exec(
                select(Interface).where(Interface.id.in_(counterpart_ids))  # type: ignore[attr-defined]
            )
            for c_if in res_counterparts.all():
                if getattr(c_if, "id", None) and getattr(c_if, "device_id", None):
                    counterpart_dev_by_if[c_if.id] = c_if.device_id  # type: ignore[assignment]

        for ln in links:
            a_if = ifmap.get(ln.a_interface_id)
            b_if = ifmap.get(ln.b_interface_id)
            if a_if and a_if.device_id == olt.id and ln.b_interface_id:
                nb_dev = counterpart_dev_by_if.get(ln.b_interface_id)
                if not nb_dev and ln.b_interface_id in iface_ids:
                    nb_dev = olt.id
                if nb_dev:
                    neigh_by_if[a_if.id].add(nb_dev)
            if b_if and b_if.device_id == olt.id and ln.a_interface_id:
                nb_dev = counterpart_dev_by_if.get(ln.a_interface_id)
                if not nb_dev and ln.a_interface_id in iface_ids:
                    nb_dev = olt.id
                if nb_dev:
                    neigh_by_if[b_if.id].add(nb_dev)

        # Use provisioned ONTs from cache key calculation (already queried above)
        ont_ids = [x.id for x in provisioned_onts]

        # Initialize counts
        pon_occ: dict[str, int] = {pi.id: 0 for pi in pon_ifaces}

        # Use Go Optical Service for path resolution (4,000× faster than Python)
        optical_client = get_optical_client()
        try:
            # Get path for each ONT (Go service Dijkstra in 10-12ms per ONT)
            for ont_id in ont_ids:
                path_data = await asyncio.to_thread(optical_client.get_path, ont_id)

                if not path_data or path_data.get("olt_id") != olt.id:
                    continue

                # Extract device IDs from path segments
                path_devs = []
                for seg in path_data.get("segments", []):
                    path_devs.append(seg.get("from_device_id"))
                if path_data.get("segments"):
                    last_seg = path_data["segments"][-1]
                    path_devs.append(last_seg.get("to_device_id"))

                # Find matching PON interface using neighbor heuristic
                candidate_ifaces = []
                for pi in pon_ifaces:
                    nb = neigh_by_if.get(pi.id, set())
                    if any(nd in path_devs for nd in nb):
                        candidate_ifaces.append(pi)
                if not candidate_ifaces:
                    # Stable fallback: first by name
                    candidate_ifaces = pon_ifaces[:]
                candidate_ifaces.sort(key=lambda x: x.name)
                chosen = candidate_ifaces[0]
                pon_occ[chosen.id] = pon_occ.get(chosen.id, 0) + 1

        except Exception as e:
            # Fallback to Python implementation if Go service unavailable
            print(f"⚠️ Go optical service failed, falling back to Python: {e}")
            for ont_id in ont_ids:
                try:
                    # Add timeout to prevent socket hang up
                    r = await asyncio.wait_for(
                        asyncio.to_thread(resolve_optical_path, ont_id),
                        timeout=2.0,  # 2 second timeout per ONT
                    )
                except (TimeoutError, Exception):
                    r = None
                if not r or r.olt_id != olt.id:
                    continue
                path_devs = [seg.src for seg in r.segments] + (
                    [r.segments[-1].dst] if r.segments else []
                )
                candidate_ifaces = []
                for pi in pon_ifaces:
                    nb = neigh_by_if.get(pi.id, set())
                    if any(nd in path_devs for nd in nb):
                        candidate_ifaces.append(pi)
                if not candidate_ifaces:
                    # Stable fallback: first by name
                    candidate_ifaces = pon_ifaces[:]
                candidate_ifaces.sort(key=lambda x: x.name)
                chosen = candidate_ifaces[0]
                pon_occ[chosen.id] = pon_occ.get(chosen.id, 0) + 1

        _olt_pon_occ_cache[cache_key] = dict(pon_occ)
        # Opportunistic cleanup to cap size
        if len(_olt_pon_occ_cache) > 1024:
            old_keys = [k for k in _olt_pon_occ_cache.keys() if k[0] != tv]
            for k in old_keys:
                _olt_pon_occ_cache.pop(k, None)
        return pon_occ


@limiter.limit("100/minute")  # Increased from 10 to support bulk device queries
@router.get("/summary/{device_id}", response_model=list[InterfaceSummaryOut])
async def get_port_summary(
    request: Request,
    device_id: str,
    s: Annotated[AsyncSession, Depends(get_async_session)],
):
    """Return detailed per-interface summaries (occupancy, capacity, effective status).

    Fast path: Use Go Port Summary Service if available (50-100× faster).
    Fallback: Python implementation with short TTL cache.
    """
    # Try Go Service first (FAST PATH - 5-10ms vs 250-700ms)
    go_client = get_port_summary_go_client()
    if go_client:
        try:
            summary = await go_client.get_port_summary(device_id)
            if summary:
                subscriber_model = await _resolve_subscriber_model_async()
                return _with_canonical_subscribers(device_id, summary, subscriber_model)
        except Exception as e:
            # Log and fall back to Python
            import logging

            logging.getLogger(__name__).warning(
                f"Port Summary Go Service failed for device {device_id}: {e}, falling back to Python"
            )

    # FALLBACK: Python implementation (SLOW PATH)
    # Fast path: serve from short TTL cache if available and fresh
    tv = PATHFINDING_STORE.version()
    cache_key = (tv, device_id)
    now = time.monotonic()
    cached = _ports_summary_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    # Acquire per-key lock to dedupe computation under concurrent requests
    lock = _ports_summary_locks.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _ports_summary_locks[cache_key] = lock
    async with lock:
        # Re-check cache inside the lock in case another coroutine filled it
        cached = _ports_summary_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        d = await s.get(Device, device_id)
    if not d:
        raise HTTPException(status_code=404, detail="Not found")

    # Build quick lookup: PortProfile capacities for PON per profile name
    profile_cap_map: dict[str, int] = {}
    if d.hardware_model_id is not None:
        res_pp = await s.exec(
            select(PortProfile).where(PortProfile.hardware_model_id == d.hardware_model_id)
        )
        for p in res_pp.all():
            if p.port_role == PortRole.PON and p.max_subscribers is not None:
                # Use profile name as lookup key (matches Interface.profile_name)
                base = (p.name or "").strip()
                if base:
                    profile_cap_map[base] = int(p.max_subscribers)

    # Load interfaces for this device
    res_if = await s.exec(select(Interface).where(Interface.device_id == d.id))
    ifaces = res_if.all()
    iface_ids = {i.id for i in ifaces}

    # Load only links attached to this device's interfaces and bucket them
    links: list[Link] = []
    links_by_if: dict[str, list[Link]] = {iid: [] for iid in iface_ids}
    if iface_ids:
        res_links = await s.exec(
            select(Link).where(
                (Link.a_interface_id.in_(iface_ids))  # type: ignore[attr-defined]
                | (Link.b_interface_id.in_(iface_ids))  # type: ignore[attr-defined]
            )
        )
        links = list(res_links.all())
        for ln in links:
            if ln.a_interface_id in links_by_if:
                links_by_if[ln.a_interface_id].append(ln)
            if ln.b_interface_id in links_by_if:
                links_by_if[ln.b_interface_id].append(ln)

    subscriber_model = await _resolve_subscriber_model_async()
    pon_occ: dict[str, int] = pon_occupancy_for(subscriber_model, d.id)

    # Helper: compute effective interface status string based on device and attached links
    def _effective_interface_status(dev: Device, iface: Interface) -> str:
        # If any attached link is effectively DOWN, mark interface as DOWN; else follow device effective
        dev_eff = evaluate_device_status(dev)
        eff_str = dev_eff.value if hasattr(dev_eff, "value") else str(dev_eff)
        for ln in links_by_if.get(iface.id, []):
            st = evaluate_link_status(ln)
            st_str = st.value if hasattr(st, "value") else str(st)
            if st_str == "DOWN":
                return "DOWN"
        return eff_str

    out: list[InterfaceSummaryOut] = []
    # Pre-map interface id -> Interface for quick fetch
    ifmap = {i.id: i for i in ifaces}

    # Optional: ONT→OLT mapping is device-level; we tie-break PON by live neighbor and name.
    # Build device->interfaces map for this device
    dev_ifaces = [i for i in ifaces]
    # Build adjacency from this device's interfaces to neighbor device IDs using links
    # Optimization: batch-fetch counterpart interfaces to avoid per-link lookups (N+1)
    neigh_by_if: dict[str, set[str]] = {i.id: set() for i in dev_ifaces}
    # Collect counterpart interface IDs not belonging to this device
    counterpart_ids: set[str] = set()
    for ln in links:
        if ln.a_interface_id and ln.a_interface_id not in iface_ids:
            counterpart_ids.add(ln.a_interface_id)
        if ln.b_interface_id and ln.b_interface_id not in iface_ids:
            counterpart_ids.add(ln.b_interface_id)
    counterpart_dev_by_if: dict[str, str] = {}
    if counterpart_ids:
        res_counterparts = await s.exec(select(Interface).where(Interface.id.in_(counterpart_ids)))  # type: ignore[attr-defined]
        for c_if in res_counterparts.all():
            if getattr(c_if, "id", None) and getattr(c_if, "device_id", None):
                counterpart_dev_by_if[c_if.id] = c_if.device_id  # type: ignore[assignment]

    # Now wire neighbors using in-memory maps only
    for ln in links:
        a_if = ifmap.get(ln.a_interface_id)
        b_if = ifmap.get(ln.b_interface_id)
        if a_if and a_if.device_id == d.id and ln.b_interface_id:
            nb_dev = counterpart_dev_by_if.get(ln.b_interface_id)
            if not nb_dev and ln.b_interface_id in iface_ids:
                nb_dev = d.id  # counterpart is on the same device
            if nb_dev:
                neigh_by_if[a_if.id].add(nb_dev)
        if b_if and b_if.device_id == d.id and ln.a_interface_id:
            nb_dev = counterpart_dev_by_if.get(ln.a_interface_id)
            if not nb_dev and ln.a_interface_id in iface_ids:
                nb_dev = d.id
            if nb_dev:
                neigh_by_if[b_if.id].add(nb_dev)

    # Safe occupancy map
    pon_occ_map: dict[str, int] = pon_occ or {}

    for iface in ifaces:
        role = getattr(iface, "port_role", None)
        occ = 0
        cap: int | None = None
        if role == PortRole.PON and d.type == DeviceType.OLT:
            # Use cached occupancy for PON interface
            occ = int(pon_occ_map.get(iface.id, 0))
            # Capacity by PortProfile.max_subscribers via profile_name
            base = (getattr(iface, "profile_name", None) or "").strip()
            if base and base in profile_cap_map:
                cap = profile_cap_map[base]
        elif role == PortRole.ACCESS:
            # ACCESS ports (AON Switch): Show actual number of connected devices (CPEs)
            # These are 1:many like PON, so don't cap at 1
            occ = len(links_by_if.get(iface.id, []))
            # ACCESS ports have no fixed capacity (can have multiple CPEs)
            cap = None
        else:
            # UPLINK, OTHER, etc.: Binary presence (0 or 1)
            occ = min(1, len(links_by_if.get(iface.id, [])))
            cap = 1

        eff = _effective_interface_status(d, iface)
        out.append(
            InterfaceSummaryOut(
                id=iface.id,
                name=iface.name,
                port_role=role,
                effective_status=eff,
                occupancy=int(occ),
                capacity=(int(cap) if cap is not None else None),
            )
        )

    # Deterministic ordering by interface name
    def _role_key(v):
        if v is None:
            return ""
        try:
            return v.value  # type: ignore[attr-defined]
        except Exception:
            return str(v)

    out = _with_canonical_subscribers(d.id, out, subscriber_model)
    out.sort(key=lambda x: (_role_key(x.port_role), x.name, x.id))
    # Store in TTL cache before returning
    _ports_summary_cache[cache_key] = (time.monotonic() + _PORTS_CACHE_TTL_SEC, out)

    # Opportunistic cleanup of expired/older-topo cache entries
    if len(_ports_summary_cache) > 2048:
        cutoff = time.monotonic()
        old_keys = [
            k for k, (exp, _) in _ports_summary_cache.items() if exp <= cutoff or k[0] != tv
        ]
        for k in old_keys:
            _ports_summary_cache.pop(k, None)

    return out


@limiter.limit("50/minute")  # Increased from 10, lower than single endpoint (more expensive)
@router.get("/summary", response_model=dict[str, list[InterfaceSummaryOut]])
async def get_bulk_port_summary(
    request: Request,
    ids: Annotated[list[str], Query(..., description="Device IDs to summarize")],
    s: Annotated[AsyncSession, Depends(get_async_session)],
):
    """Bulk variant: returns a mapping device_id -> list[InterfaceSummaryOut].

    Fast path: Use Go Port Summary Service if available (50-100× faster).
    Fallback: Python implementation with short TTL cache.
    """
    if len(ids) > MAX_BULK_IDS:
        raise HTTPException(status_code=400, detail=f"Too many IDs (max {MAX_BULK_IDS})")
    if not ids:
        return {}

    # Try Go Service first (FAST PATH - 10-20ms vs 2-5s for 200 devices)
    go_client = get_port_summary_go_client()
    if go_client:
        try:
            result = await go_client.get_bulk_port_summary(ids)
            if result:
                subscriber_model = await _resolve_subscriber_model_async()
                return {
                    did: _with_canonical_subscribers(did, rows, subscriber_model)
                    for did, rows in result.items()
                }
        except Exception as e:
            # Log and fall back to Python
            logging.getLogger(__name__).warning(
                f"Port Summary Go Service bulk failed for {len(ids)} devices: {e}, falling back to Python"
            )

    # FALLBACK: Python implementation (SLOW PATH)
    """Bulk variant: returns a mapping device_id -> list[InterfaceSummaryOut].

    Optimized to batch-fetch all devices, interfaces, and links in 3 queries instead of N loops.
    """

    # Limit & deduplicate ids while preserving stable order
    if len(ids) > MAX_BULK_IDS:
        raise HTTPException(status_code=400, detail=f"Too many device IDs (>{MAX_BULK_IDS})")
    seen = set()
    ordered_ids = [x for x in ids if not (x in seen or seen.add(x))]

    if not ordered_ids:
        return {}

    # OPTIMIZATION: Batch-fetch all devices in ONE query
    res_devices = await s.exec(select(Device).where(Device.id.in_(ordered_ids)))  # type: ignore[attr-defined]
    devices_by_id: dict[str, Device] = {d.id: d for d in res_devices.all()}

    # Collect hardware model IDs for PortProfile lookup
    hw_model_ids = {d.hardware_model_id for d in devices_by_id.values() if d.hardware_model_id}
    profile_cap_map: dict[tuple[int | str, str], int] = (
        {}
    )  # (hw_model_id, profile_name) -> capacity

    if hw_model_ids:
        res_pp = await s.exec(
            select(PortProfile).where(PortProfile.hardware_model_id.in_(hw_model_ids))  # type: ignore[attr-defined]
        )
        for p in res_pp.all():
            if (
                p.port_role == PortRole.PON
                and p.max_subscribers is not None
                and p.hardware_model_id
            ):
                base = (p.name or "").strip()
                if base:
                    profile_cap_map[(p.hardware_model_id, base)] = int(p.max_subscribers)

    # OPTIMIZATION: Batch-fetch all interfaces in ONE query
    res_if = await s.exec(select(Interface).where(Interface.device_id.in_(ordered_ids)))  # type: ignore[attr-defined]
    ifaces_by_device: dict[str, list[Interface]] = {did: [] for did in ordered_ids}
    all_iface_ids: set[str] = set()

    for iface in res_if.all():
        if iface.device_id in ifaces_by_device:
            ifaces_by_device[iface.device_id].append(iface)
            all_iface_ids.add(iface.id)

    # OPTIMIZATION: Batch-fetch all links in ONE query
    links_by_if: dict[str, list[Link]] = {iid: [] for iid in all_iface_ids}
    if all_iface_ids:
        res_links = await s.exec(
            select(Link).where(
                (Link.a_interface_id.in_(all_iface_ids))  # type: ignore[attr-defined]
                | (Link.b_interface_id.in_(all_iface_ids))  # type: ignore[attr-defined]
            )
        )
        for ln in res_links.all():
            if ln.a_interface_id in links_by_if:
                links_by_if[ln.a_interface_id].append(ln)
            if ln.b_interface_id in links_by_if:
                links_by_if[ln.b_interface_id].append(ln)

    # Helper: compute effective interface status
    def _effective_interface_status(dev: Device, iface: Interface) -> str:
        dev_eff = evaluate_device_status(dev)
        eff_str = dev_eff.value if hasattr(dev_eff, "value") else str(dev_eff)
        for ln in links_by_if.get(iface.id, []):
            st = evaluate_link_status(ln)
            st_str = st.value if hasattr(st, "value") else str(st)
            if st_str == "DOWN":
                return "DOWN"
        return eff_str

    # Process each device using batch-fetched data
    results: dict[str, list[InterfaceSummaryOut]] = {}
    tv = PATHFINDING_STORE.version()
    subscriber_model = await _resolve_subscriber_model_async()

    for did in ordered_ids:
        dev = devices_by_id.get(did)
        if not dev:
            # Skip missing devices (404 in single endpoint, but here we skip)
            continue

        # Check cache first
        cache_key = (tv, did)
        now = time.monotonic()
        cached = _ports_summary_cache.get(cache_key)
        if cached and cached[0] > now:
            results[did] = cached[1]
            continue

        ifaces = ifaces_by_device.get(did, [])
        out: list[InterfaceSummaryOut] = []

        # Build capacity map for this device
        device_profile_cap: dict[str, int] = {}
        if dev.hardware_model_id:
            for (hw_id, prof_name), cap in profile_cap_map.items():
                if hw_id == dev.hardware_model_id:
                    device_profile_cap[prof_name] = cap

        pon_occ_map: dict[str, int] = pon_occupancy_for(subscriber_model, dev.id)

        for iface in ifaces:
            role = getattr(iface, "port_role", None)
            occ = 0
            cap: int | None = None

            if role == PortRole.PON and dev.type == DeviceType.OLT:
                occ = int(pon_occ_map.get(iface.id, 0))
                base = (getattr(iface, "profile_name", None) or "").strip()
                if base and base in device_profile_cap:
                    cap = device_profile_cap[base]
            elif role == PortRole.ACCESS:
                # ACCESS ports (AON Switch): Show actual number of connected devices (CPEs)
                occ = len(links_by_if.get(iface.id, []))
                cap = None  # No fixed capacity for ACCESS ports
            else:
                # UPLINK, OTHER, etc.: Binary presence (0 or 1)
                occ = min(1, len(links_by_if.get(iface.id, [])))
                cap = 1

            eff = _effective_interface_status(dev, iface)
            out.append(
                InterfaceSummaryOut(
                    id=iface.id,
                    name=iface.name,
                    port_role=role,
                    effective_status=eff,
                    occupancy=int(occ),
                    capacity=(int(cap) if cap is not None else None),
                )
            )

        # Deterministic ordering
        def _role_key(v):
            if v is None:
                return ""
            try:
                return v.value  # type: ignore[attr-defined]
            except Exception:
                return str(v)

        out = _with_canonical_subscribers(dev.id, out, subscriber_model)
        out.sort(key=lambda x: (_role_key(x.port_role), x.name, x.id))

        # Cache result
        _ports_summary_cache[cache_key] = (time.monotonic() + _PORTS_CACHE_TTL_SEC, out)
        results[did] = out

    # Opportunistic cache cleanup
    if len(_ports_summary_cache) > 2048:
        cutoff = time.monotonic()
        old_keys = [
            k for k, (exp, _) in _ports_summary_cache.items() if exp <= cutoff or k[0] != tv
        ]
        for k in old_keys:
            _ports_summary_cache.pop(k, None)

    return results


@router.get("/ont-list/{device_id}", response_model=list[dict])
def list_onts_under(device_id: str):
    """Return a compact list of ONT/AON_CPE devices contained by the given container.

    Each item: { id, name, type }
    """
    with get_session() as s:
        parent = s.get(Device, device_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Not found")
        rows = list(
            s.exec(
                select(Device).where(
                    (Device.parent_container_id == parent.id)
                    & (
                        (Device.type == DeviceType.ONT)
                        | (Device.type == DeviceType.BUSINESS_ONT)
                        | (Device.type == DeviceType.AON_CPE)
                    )
                )
            ).all()
        )
        # Sort deterministically by type then name then id
        rows.sort(key=lambda r: (r.type.value, r.name, r.id))
        return [{"id": r.id, "name": r.name, "type": r.type.value} for r in rows]


__all__ = ["router"]
