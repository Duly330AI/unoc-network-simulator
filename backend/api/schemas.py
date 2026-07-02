"""Pydantic schemas.
Phase B minimal set.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select

from backend.db import get_session, init_db
from backend.models import (
    AdminStatus,
    Device,
    DeviceRole,
    DeviceType,
    HardwareModel,
    InterfaceRole,
    LinkType,
    PortRole,
    Status,
)
from backend.services.catalog_effective import (
    get_effective_device_capacity_mbps,
    get_effective_sensitivity_dbm,
    get_effective_tx_power_dbm,
)
from backend.services.splitter_service import compute_splitter_usage
from backend.services.status_service import evaluate_device_status


class HealthResponse(BaseModel):
    status: str


class MetadataResponse(BaseModel):
    app: str
    version: str
    specRevision: str
    debug: bool
    timestamp: str


class LayoutPositionPatch(BaseModel):
    id: str
    x: float
    y: float
    userPinned: bool | None = None
    systemPinned: bool | None = None


class LayoutPositionsPatchRequest(BaseModel):
    version: int | None = None
    positions: list[LayoutPositionPatch]


class LayoutPositionsPatchResponse(BaseModel):
    version: int
    applied: int


class DeviceOut(BaseModel):
    id: str
    name: str
    type: DeviceType
    status: Status
    provisioned: bool
    role: DeviceRole
    admin_override_status: Status | None = None
    tx_power_dbm: float | None = None
    sensitivity_min_dbm: float | None = None
    insertion_loss_db: float | None = None
    # Signal budget (TASK-035)
    signal_power_dbm: float | None = None
    signal_margin_db: float | None = None
    attenuation_db: float | None = None  # Total optical path attenuation
    signal_status: Device.SignalStatus | None = None
    parent_container_id: str | None = None
    slot_id: str | None = None
    # Tariff assignment (TASK-401)
    tariff_id: int | None = None
    # HardwareModel linkage (TASK-522)
    hardware_model_id: int | None = None
    # Optional enrichment used by list_devices(include_interfaces=true)
    interfaces: list[dict] | None = None
    # L3 context: default VRF name for the device
    device_default_vrf_name: str | None = None
    # Derived parameters bundle (TASK-523)
    parameters: dict | None = None
    subscribers: int | None = None

    @classmethod
    def from_model(cls, d):  # type: ignore[no-untyped-def]
        dynamic_status = evaluate_device_status(d)
        # Compute derived parameters
        init_db()
        with get_session() as s:
            eff_tx = get_effective_tx_power_dbm(s, d)
            eff_sens = get_effective_sensitivity_dbm(s, d)
            eff_cap = get_effective_device_capacity_mbps(s, d)
            # Load catalog defaults to show in response (if available)
            catalog_tx = None
            catalog_sens = None
            catalog_cap = None
            if getattr(d, "hardware_model_id", None) is not None:
                m = s.exec(
                    select(HardwareModel).where(HardwareModel.id == d.hardware_model_id)
                ).first()
                if m:
                    catalog_tx = m.tx_power_dbm
                    catalog_sens = m.sensitivity_min_dbm
                    catalog_cap = int(m.capacity_gbps * 1000) if m.capacity_gbps else None
        params: dict[str, Any] = {
            "optical": {
                "effective_tx_power_dbm": eff_tx,
                "catalog_tx_power_dbm": catalog_tx,
                "tx_power_overridden": getattr(d, "tx_power_dbm", None) is not None,
                "effective_sensitivity_min_dbm": eff_sens,
                "catalog_sensitivity_min_dbm": catalog_sens,
                "sensitivity_overridden": getattr(d, "sensitivity_min_dbm", None) is not None,
            },
            "capacity": {
                "effective_device_capacity_mbps": eff_cap,
                "catalog_device_capacity_mbps": catalog_cap,
                "device_capacity_overridden": getattr(d, "capacity", None) is not None,
            },
        }
        # Splitter-specific enrichment
        try:
            if getattr(d, "type", None) == DeviceType.SPLITTER:
                ports_total, ports_used, downstream_onts = compute_splitter_usage(s, d)
                params["splitter"] = {
                    "ports_total": ports_total,
                    "ports_used": ports_used,
                    "downstream_onts": downstream_onts,
                }
        except Exception:  # pragma: no cover - defensive
            pass
        # Compatibility flatten for UI components that expect parameters.effective_capacity_mbps
        # while keeping the structured parameters.capacity.* payload intact.
        try:
            params["effective_capacity_mbps"] = eff_cap
        except Exception:  # pragma: no cover - defensive only
            pass
        # Resolve default VRF name if assigned
        device_default_vrf_name: str | None = None
        try:
            init_db()
            with get_session() as s2:
                vrf_id = getattr(d, "vrf_id", None)
                if vrf_id is not None:
                    from backend.models import VRF

                    v = s2.get(VRF, vrf_id)
                    if v:
                        device_default_vrf_name = v.name
        except Exception:  # pragma: no cover - defensive
            device_default_vrf_name = None
        # Ensure field presence even when not set (empty string ensures inclusion with exclude_none)
        if device_default_vrf_name is None:
            device_default_vrf_name = ""
        return cls(
            id=d.id,
            name=d.name,
            type=d.type,
            status=dynamic_status,
            provisioned=getattr(d, "provisioned", False),
            role=d.derive_role(),
            admin_override_status=getattr(d, "admin_override_status", None),
            tx_power_dbm=getattr(d, "tx_power_dbm", None),
            sensitivity_min_dbm=getattr(d, "sensitivity_min_dbm", None),
            insertion_loss_db=getattr(d, "insertion_loss_db", None),
            signal_power_dbm=getattr(d, "signal_power_dbm", None),
            signal_margin_db=getattr(d, "signal_margin_db", None),
            attenuation_db=getattr(d, "attenuation_db", None),  # ✅ FIXED: Include attenuation_db
            signal_status=getattr(d, "signal_status", None),
            parent_container_id=getattr(d, "parent_container_id", None),
            slot_id=getattr(d, "slot_id", None),
            tariff_id=getattr(d, "tariff_id", None),
            hardware_model_id=getattr(d, "hardware_model_id", None),
            device_default_vrf_name=device_default_vrf_name,
            parameters=params,
            subscribers=None,
        )


class InterfaceOut(BaseModel):
    id: str
    device_id: str
    name: str
    mac_address: str | None = None
    role: InterfaceRole | None = None
    admin_status: AdminStatus
    status: Status
    capacity: int | None = None


class LinkOut(BaseModel):
    id: str
    a_interface_id: str
    b_interface_id: str
    status: Status
    effective_status: str | None = None
    kind: LinkType
    admin_override_status: Status | None = None
    protection_mode: str | None = None
    # Optical extensions (TASK-037)
    length_km: float | None = None
    physical_medium_id: int | None = None


class LinkCreate(BaseModel):
    id: str
    a_interface_id: str
    b_interface_id: str
    kind: LinkType = LinkType.FIBER
    status: Status = Status.UP
    admin_override_status: Status | None = None
    protection_mode: str | None = None
    # Optional optical params; validated in endpoint
    length_km: float | None = None
    physical_medium_id: int | None = None


class LinkResolvedOut(LinkOut):
    a_device_id: str
    b_device_id: str
    rule_id: str | None = None


class LinkUpdate(BaseModel):
    status: Status | None = None
    admin_override_status: Status | None = None
    # Optical extensions (TASK-037)
    length_km: float | None = None
    physical_medium_id: int | None = None


# ---- Device CRUD (TASK-010) ----


class DeviceCreate(BaseModel):
    id: str
    name: str
    type: DeviceType
    status: Status = Status.UP
    parent_container_id: str | None = None
    properties: dict | None = None
    hardware_model_id: int | None = None


class DeviceUpdate(BaseModel):
    name: str | None = None
    status: Status | None = None
    parent_container_id: str | None = None
    slot_id: str | None = None
    properties: dict | None = None
    admin_override_status: Status | None = None
    tx_power_dbm: float | None = None
    sensitivity_min_dbm: float | None = None
    insertion_loss_db: float | None = None
    tariff_id: int | None = None
    # Allow assigning or changing hardware model on update
    hardware_model_id: int | None = None


class ProvisionResponse(BaseModel):
    device: DeviceOut


# ---- Metrics (TASK-054) ----


class DeviceMetricOut(BaseModel):
    bps: float
    utilization: float
    version: int | None = 0
    upstream_bps: float | None = None
    downstream_bps: float | None = None


class MetricsSnapshotResponse(BaseModel):
    lastTick: int
    devices: dict[str, DeviceMetricOut]
    links: dict[str, DeviceMetricOut] | None = None
    # Per-device per-interface metrics (optional)
    ports: dict[str, dict[str, DeviceMetricOut]] | None = None
    # Per PON segment (OLT PON-port <-> ODF) aggregated metrics (optional)
    segments: dict[str, SegmentSnapshotOut] | None = None


# ---- Config (TASK-061) ----


class MetricsConfig(BaseModel):
    EPSILON_METRICS_DELTA: float
    UTILIZATION_BUCKETS: list[int]


class AppConfigResponse(BaseModel):
    metrics: MetricsConfig
    # Feature flags exposed to frontend (Phase 0 only; default false)
    flags: dict[str, bool]


# ---- Tariff (TASK-401/402) ----


class InterfaceSummaryOut(BaseModel):
    id: str
    name: str
    port_role: PortRole | None = None
    effective_status: str | None = None
    occupancy: int
    capacity: int | None = None
    provisioned_onts_count: int | None = None
    provisioned_cpes_count: int | None = None
    max_capacity: int | None = None
    utilization: float | None = None


class TariffOut(BaseModel):
    id: int
    name: str
    max_up_mbps: float
    max_down_mbps: float
    technology: str | None = None


# ---- Segments (Phase 2 GPON) ----


class SegmentSnapshotOut(BaseModel):
    # Identity and topology anchors
    id: str  # stable key (pon_port_id::odf_id)
    olt_id: str
    pon_port_id: str
    odf_id: str
    # Occupancy
    subscribers_count: int
    subscribers_max: int | None = None
    # Capacity (bps)
    capacity_down_bps: float
    capacity_up_bps: float
    # Demand (bps)
    demand_down_bps: float
    demand_up_bps: float
    # Used (after shaping) (bps)
    used_down_bps: float
    used_up_bps: float
    # Headroom (bps)
    headroom_down_bps: float
    headroom_up_bps: float
    # State
    congested: bool


# ---- Tools: Terminal Viewer groundwork (Phase 5) ----


class PingRequest(BaseModel):
    source_device_id: str
    target_device_id: str | None = None
    target_ip: str | None = None


class PingResponse(BaseModel):
    outcome: str  # "success" | "unreachable"
    hops: list[str]
    rtt_ms: float | None = None


class TracerouteHop(BaseModel):
    hop: int
    device_id: str
    rtt_ms: float | None = None
    success: bool = True


class TracerouteRequest(BaseModel):
    source_device_id: str
    target_device_id: str | None = None
    target_ip: str | None = None
    max_hops: int = 8


class TracerouteResponse(BaseModel):
    outcome: str  # "reached" | "unreachable" | "ttl_exceeded"
    hops: list[TracerouteHop]
    final_device_id: str | None = None


# ---- Batch Operations (Week 3 Day 14) ----


class LinkCreateSpec(BaseModel):
    """Single link specification for batch creation."""

    a_interface_id: int
    b_interface_id: int
    length_km: float = 0.0
    status: str = "active"
    metadata: dict[str, str] = {}


class BatchLinkCreateRequest(BaseModel):
    """Request for batch link creation."""

    links: list[LinkCreateSpec]
    dry_run: bool = False
    skip_optical_recompute: bool = False
    request_id: str | None = None


class LinkCreationFailure(BaseModel):
    """Failure details for a single link creation."""

    index: int
    a_interface_id: int
    b_interface_id: int
    error_code: str
    error_message: str


class BatchCreateLinksResponse(BaseModel):
    """Response for batch link creation."""

    created_link_ids: list[int]
    failed_links: list[LinkCreationFailure]
    total_requested: int
    total_created: int
    duration_ms: int
    request_id: str
    backend: str  # "go" or "python"


class LinkDeletionFailure(BaseModel):
    """Failure details for a single link deletion."""

    link_id: int
    error_code: str
    error_message: str


class BatchDeleteLinksRequest(BaseModel):
    """Request for batch link deletion."""

    link_ids: list[int]
    skip_optical_recompute: bool = False
    request_id: str | None = None


class BatchDeleteLinksResponse(BaseModel):
    """Response for batch link deletion."""

    deleted_link_ids: list[int]
    failed_links: list[LinkDeletionFailure]
    total_requested: int
    total_deleted: int
    duration_ms: int
    request_id: str
    backend: str  # "go" or "python"
