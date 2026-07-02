"""Debug-only audit for subscriber aggregation correctness."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from backend.services.layer_validation import validate_layer_isolation
from backend.services.layered_state_model import resolve_layered_device_state
from backend.services.optical_physics_model import resolve_optical_physics_state
from backend.services.subscriber_model import SUBSCRIBER_SOURCE, resolve_subscriber_model


def _node(model: dict[str, Any], device_id: str) -> dict[str, Any]:
    return dict(model.get("resolved_subscribers", {}).get(device_id, {}))


def _wrong_source_warnings(validation: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for violation in validation.get("violations", []):
        if violation.get("target_layer") != "L4_SERVICE":
            continue
        warnings.append(
            {
                "code": "INVALID_AGGREGATION_SOURCE",
                "device_id": violation.get("device_id"),
                "source_layer": violation.get("source_layer"),
                "target_layer": violation.get("target_layer"),
                "source_field": violation.get("source_field"),
                "severity": violation.get("severity"),
                "message": "subscriber_count must be derived only from L4_PROVISIONING_GRAPH",
            }
        )
    return warnings


def build_aggregation_audit(session: Session) -> dict[str, Any]:
    model = resolve_subscriber_model(session)
    optical_state = resolve_optical_physics_state(session)
    device_state = resolve_layered_device_state(session, model, optical_state)
    validation = validate_layer_isolation(device_state, model, optical_state)

    device_breakdown: dict[str, dict[str, Any]] = {}
    for device_id, node in sorted(model.get("resolved_subscribers", {}).items()):
        device_type = node.get("type")
        if device_type not in {"OLT", "AON_SWITCH"}:
            continue
        if device_type == "OLT":
            correct = sum(model.get("pon_occupancy", {}).get(device_id, {}).values())
            port_breakdown = model.get("pon_ports", {}).get(device_id, {})
        else:
            correct = sum(model.get("aon_access_occupancy", {}).get(device_id, {}).values())
            port_breakdown = model.get("aon_access_ports", {}).get(device_id, {})
        reported = int(node.get("subscribers") or 0)
        delta = reported - correct
        device_breakdown[device_id] = {
            "device_id": device_id,
            "device_type": device_type,
            "correct_subscriber_count": correct,
            "reported_subscriber_count": reported,
            "mismatch_delta": delta,
            "aggregation_source": node.get("aggregation_source"),
            "source_of_wrong_calculation": "none" if delta == 0 else node.get("aggregation_source"),
            "port_breakdown": port_breakdown,
        }

    oversubscription = [
        decision
        for decision in model.get("mapping_decisions", [])
        if decision.get("reason") == "aon_access_port_oversubscribed_1_to_1"
    ]

    return {
        "source_of_truth": SUBSCRIBER_SOURCE,
        "forbidden_sources": ["MAC_TABLE", "IP_PATH", "OPTICAL_LOSS", "TRAFFIC_FLOW", "PORT_UTILIZATION"],
        "global": model.get("global", {}),
        "olt": {
            device_id: data for device_id, data in device_breakdown.items() if data["device_type"] == "OLT"
        },
        "aon": {
            device_id: data
            for device_id, data in device_breakdown.items()
            if data["device_type"] == "AON_SWITCH"
        },
        "device_breakdown": device_breakdown,
        "oversubscription_warnings": oversubscription,
        "invalid_aggregation_source_warnings": _wrong_source_warnings(validation),
        "validation_summary": validation.get("summary", {}),
    }


__all__ = ["build_aggregation_audit"]