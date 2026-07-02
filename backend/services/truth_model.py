"""Canonical debug truth model for physical, service, and analytics realities."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlmodel import Session, select

from backend.models import Device, Interface, Link
from backend.services.count_semantics import build_count_semantics
from backend.services.subscriber_model import CPE_TYPES, ONT_TYPES, resolve_subscriber_model

PHYSICAL_TRUTH = "PHYSICAL_TRUTH"
SERVICE_TRUTH = "SERVICE_TRUTH"
ANALYTICS_TRUTH = "ANALYTICS_TRUTH"


def _type_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").upper()


def _severity(delta: int, effective_count: int) -> str:
    absolute = abs(delta)
    if absolute == 0:
        return "none"
    if effective_count == 0 or absolute >= 2:
        return "high"
    return "medium"


def _explain_conflict(device_id: str, device_type: str, physical: int, service: int, analytics: int) -> str:
    if physical != service and service == analytics:
        return (
            f"{device_id} has {physical} physical {device_type} attachment(s), "
            f"while SERVICE_TRUTH and ANALYTICS_TRUTH agree on {service}."
        )
    if service != analytics and physical == service:
        return (
            f"{device_id} has {service} service-mapped element(s), but analytics reports {analytics}; "
            "this usually means an effective-count rule such as 1:1 access-port enforcement applied."
        )
    return (
        f"{device_id} differs across truth tiers: physical={physical}, service={service}, "
        f"analytics={analytics}. Inspect service mapping decisions for the deterministic cause."
    )


def build_truth_model(session: Session) -> dict[str, Any]:
    devices = list(session.exec(select(Device)).all())
    interfaces = list(session.exec(select(Interface)).all())
    links = list(session.exec(select(Link)).all())
    subscriber_model = resolve_subscriber_model(session)
    count_model = build_count_semantics(session)

    physical_by_type = Counter(_type_name(device.type) for device in devices)
    service_counts = subscriber_model.get("global", {}).get("subscriber", {})
    analytics_counts = count_model.get("global", {})

    physical_snapshot = {
        "truth_tier": PHYSICAL_TRUTH,
        "owner": "topology graph only",
        "read_only": True,
        "devices_total": len(devices),
        "ports_total": len(interfaces),
        "links_total": len(links),
        "device_counts_by_type": dict(sorted(physical_by_type.items())),
    }
    service_snapshot = {
        "truth_tier": SERVICE_TRUTH,
        "owner": "L4 provisioning graph only",
        "read_only": True,
        "subscriber_counts": service_counts,
        "mapping_decisions": subscriber_model.get("mapping_decisions", []),
        "resolved_subscribers": subscriber_model.get("resolved_subscribers", {}),
    }
    analytics_snapshot = {
        "truth_tier": ANALYTICS_TRUTH,
        "owner": "derived metrics only",
        "read_only": True,
        "count_semantics": count_model,
        "global_counts": analytics_counts,
    }

    conflicts: list[dict[str, Any]] = []
    for device_id, counts in sorted(count_model.get("devices", {}).items()):
        device_type = counts.get("device_type")
        if device_type not in {"OLT", "AON_SWITCH", "PON", *ONT_TYPES, *CPE_TYPES}:
            continue
        physical = int(counts.get("physical_count") or 0)
        service = int(counts.get("provisioned_count") or 0)
        analytics = int(counts.get("effective_count") or 0)
        if physical == service == analytics:
            continue
        delta = analytics - service
        conflicts.append(
            {
                "type": "PHYSICAL_SERVICE_MISMATCH",
                "device_id": device_id,
                "device_type": device_type,
                "severity": _severity(delta if delta else physical - service, analytics),
                "source_layers": [PHYSICAL_TRUTH, SERVICE_TRUTH, ANALYTICS_TRUTH],
                "physical_count": physical,
                "service_count": service,
                "analytics_count": analytics,
                "mismatch_delta": delta if delta else physical - service,
                "explanation": _explain_conflict(device_id, str(device_type), physical, service, analytics),
            }
        )

    return {
        "model": "TruthResolver",
        "rules": {
            "PHYSICAL_TRUTH": "topology graph only: devices, ports, links",
            "SERVICE_TRUTH": "L4 provisioning graph only: subscribers, ONTs, CPE mapping",
            "ANALYTICS_TRUTH": "derived metrics only: counts, utilization, aggregation",
            "no_overwrite": "No truth tier may overwrite another; tiers are read-only sources for diagnostics.",
            "ui_rule": "UI must explicitly choose physical view, service view, or analytics view; implicit mixing is forbidden.",
        },
        "physical_snapshot": physical_snapshot,
        "service_snapshot": service_snapshot,
        "analytics_snapshot": analytics_snapshot,
        "conflicts": conflicts,
        "summary": {
            "conflict_count": len(conflicts),
            "high_severity_count": sum(1 for item in conflicts if item.get("severity") == "high"),
            "truth_tiers": [PHYSICAL_TRUTH, SERVICE_TRUTH, ANALYTICS_TRUTH],
        },
    }


__all__ = ["ANALYTICS_TRUTH", "PHYSICAL_TRUTH", "SERVICE_TRUTH", "build_truth_model"]