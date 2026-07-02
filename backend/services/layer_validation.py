"""Runtime diagnostics for L1/L2/L3/L4 isolation.

The validation engine is intentionally observational: it reports suspected
cross-layer leaks but never mutates topology, status, subscribers, routing, or
optical state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.subscriber_model import SUBSCRIBER_SOURCE

LAYERS = ("L1_PHYSICAL", "L2_DATAPLANE", "L3_NETWORK", "L4_SERVICE")

L1_FORBIDDEN_L4_KEYS = {"subscriber", "subscribers", "subscriber_ids", "subscriber_domain"}
L4_FORBIDDEN_L1_KEYS = {
    "attenuation",
    "capacity",
    "connector_loss",
    "fiber_attenuation",
    "insertion_loss",
    "link_budget",
    "optical",
    "power_dbm",
    "rx_power",
    "splitter_loss",
    "tx_power",
}
L2_FORBIDDEN_L3_KEYS = {"ip", "ip_address", "next_hop", "prefix", "route", "routes", "vrf"}
L3_FORBIDDEN_L2_KEYS = {"bridge_domain", "mac", "mac_address", "mac_entries", "switching"}
INVALID_SUBSCRIBER_SOURCE_TERMS = {"mac", "mac_address", "optical", "loss", "traffic", "flow", "bps", "ip_path"}


@dataclass(frozen=True, slots=True)
class LayerViolation:
    device_id: str | None
    source_layer: str
    target_layer: str
    source_field: str
    target_field: str
    rule: str
    message: str
    severity: int
    level: str = "WARNING"

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "source_layer": self.source_layer,
            "target_layer": self.target_layer,
            "source_field": self.source_field,
            "target_field": self.target_field,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
            "level": self.level,
        }


def _key_text(value: Any) -> str:
    return str(value or "").lower()


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        rows: list[tuple[str, Any]] = []
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten(nested, path))
        return rows
    if isinstance(value, list):
        rows = []
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]"
            rows.extend(_flatten(nested, path))
        return rows
    return [(prefix, value)]


def _path_has_any(path: str, terms: set[str]) -> bool:
    normalized = _key_text(path).replace("-", "_")
    return any(term in normalized for term in terms)


class LayerValidationEngine:
    """Validates diagnostic layer state for visible cross-layer leakage."""

    def validate(
        self,
        device_state: dict[str, Any],
        subscriber_model: dict[str, Any],
        optical_state: dict[str, Any],
    ) -> dict[str, Any]:
        violations: list[LayerViolation] = []
        devices = device_state.get("devices", {}) if isinstance(device_state, dict) else {}
        for device_id, state in devices.items():
            violations.extend(self._validate_device_state(str(device_id), state))

        violations.extend(self._validate_subscriber_model(subscriber_model))
        violations.extend(self._validate_optical_state(optical_state))

        violation_dicts = [item.as_dict() for item in violations]
        device_ids = sorted(str(key) for key in devices.keys())
        per_device = {
            device_id: self._device_validation_state(device_id, violation_dicts)
            for device_id in device_ids
        }
        return {
            "engine": "LayerValidationEngine",
            "mode": "diagnostic_warning_only",
            "rules": [
                "L1_PHYSICAL may not access L4_SERVICE data",
                "L4_SERVICE may not depend on L1 signal metrics",
                "L2_DATAPLANE may not access L3_NETWORK routing/IP fields",
                "L3_NETWORK may not access L2_DATAPLANE MAC fields",
                "anti-leak checks are warnings and never crash runtime services",
            ],
            "violations": violation_dicts,
            "summary": {
                "total_violations": len(violation_dicts),
                "max_severity": max((item["severity"] for item in violation_dicts), default=0),
                "is_pure": len(violation_dicts) == 0,
            },
            "devices": per_device,
        }

    def _validate_device_state(self, device_id: str, state: dict[str, Any]) -> list[LayerViolation]:
        violations: list[LayerViolation] = []
        physical = state.get("physical", {}) if isinstance(state, dict) else {}
        dataplane = state.get("dataplane", {}) if isinstance(state, dict) else {}
        network = state.get("network", {}) if isinstance(state, dict) else {}
        service = state.get("service", {}) if isinstance(state, dict) else {}

        for path, _value in _flatten(physical, "physical"):
            if _path_has_any(path, L1_FORBIDDEN_L4_KEYS):
                violations.append(
                    LayerViolation(
                        device_id=device_id,
                        source_layer="L4_SERVICE",
                        target_layer="L1_PHYSICAL",
                        source_field="subscriber.*",
                        target_field=path,
                        rule="L1_PHYSICAL may not access L4_SERVICE data",
                        message="Physical state exposes service subscriber semantics.",
                        severity=80,
                    )
                )

        for path, _value in _flatten(service, "service"):
            if _path_has_any(path, L4_FORBIDDEN_L1_KEYS):
                violations.append(
                    LayerViolation(
                        device_id=device_id,
                        source_layer="L1_PHYSICAL",
                        target_layer="L4_SERVICE",
                        source_field="physical.optical_or_capacity.*",
                        target_field=path,
                        rule="L4_SERVICE may not depend on L1 signal metrics",
                        message="Service state exposes physical optical/capacity semantics.",
                        severity=85,
                    )
                )

        for path, _value in _flatten(dataplane, "dataplane"):
            if _path_has_any(path, L2_FORBIDDEN_L3_KEYS):
                violations.append(
                    LayerViolation(
                        device_id=device_id,
                        source_layer="L3_NETWORK",
                        target_layer="L2_DATAPLANE",
                        source_field="network.ip_or_route.*",
                        target_field=path,
                        rule="L2_DATAPLANE may not access L3_NETWORK routing/IP fields",
                        message="Dataplane state exposes network routing/IP semantics.",
                        severity=70,
                    )
                )

        for path, _value in _flatten(network, "network"):
            if _path_has_any(path, L3_FORBIDDEN_L2_KEYS):
                violations.append(
                    LayerViolation(
                        device_id=device_id,
                        source_layer="L2_DATAPLANE",
                        target_layer="L3_NETWORK",
                        source_field="dataplane.mac.*",
                        target_field=path,
                        rule="L3_NETWORK may not access L2_DATAPLANE MAC fields",
                        message="Network state exposes dataplane MAC semantics.",
                        severity=70,
                    )
                )

        return violations

    def _validate_subscriber_model(self, subscriber_model: dict[str, Any]) -> list[LayerViolation]:
        violations: list[LayerViolation] = []
        flat = _flatten(subscriber_model, "subscriber_model")
        source_paths = (
            "subscriber_model.global",
            "subscriber_model.mapping_decisions",
            "subscriber_model.resolved_subscribers",
        )
        for path, value in flat:
            if not path.startswith(source_paths):
                continue
            value_text = _key_text(value)
            if path.endswith("source") or path.endswith("aggregation_source"):
                if value_text and value_text.upper() != SUBSCRIBER_SOURCE:
                    violations.append(
                        LayerViolation(
                            device_id=self._device_from_path(path),
                            source_layer="UNKNOWN",
                            target_layer="L4_SERVICE",
                            source_field=path,
                            target_field="subscriber_model",
                            rule="INVALID_AGGREGATION_SOURCE",
                            message="subscriber_count must be derived only from L4_PROVISIONING_GRAPH",
                            severity=95,
                        )
                    )
            if _path_has_any(path, {"mac", "mac_address"}) or any(
                term in value_text for term in {"mac", "mac_address"}
            ):
                violations.append(
                    LayerViolation(
                        device_id=self._device_from_path(path),
                        source_layer="L2_DATAPLANE",
                        target_layer="L4_SERVICE",
                        source_field=path,
                        target_field="subscriber_model",
                        rule="subscriber_count derived from MAC table",
                        message="Subscriber diagnostics expose MAC-derived fields.",
                        severity=90,
                    )
                )
            if _path_has_any(path, L4_FORBIDDEN_L1_KEYS) or any(
                term in value_text for term in INVALID_SUBSCRIBER_SOURCE_TERMS
            ):
                violations.append(
                    LayerViolation(
                        device_id=self._device_from_path(path),
                        source_layer="L1_PHYSICAL",
                        target_layer="L4_SERVICE",
                        source_field=path,
                        target_field="subscriber_model",
                        rule="optical loss affecting subscriber count directly",
                        message="Subscriber diagnostics expose physical optical/capacity fields.",
                        severity=90,
                    )
                )
        return violations

    def _validate_optical_state(self, optical_state: dict[str, Any]) -> list[LayerViolation]:
        violations: list[LayerViolation] = []
        for path, _value in _flatten(optical_state, "optical_state"):
            if path.startswith("optical_state.rules"):
                continue
            if _path_has_any(path, {"subscriber", "subscriber_count"}):
                violations.append(
                    LayerViolation(
                        device_id=self._device_from_path(path),
                        source_layer="L4_SERVICE",
                        target_layer="L1_PHYSICAL",
                        source_field=path,
                        target_field="optical_state",
                        rule="L1_PHYSICAL may not access L4_SERVICE data",
                        message="Optical physics diagnostics expose service subscriber fields.",
                        severity=90,
                    )
                )
            if _path_has_any(path, {"mac", "mac_address"}):
                violations.append(
                    LayerViolation(
                        device_id=self._device_from_path(path),
                        source_layer="L2_DATAPLANE",
                        target_layer="L1_PHYSICAL",
                        source_field=path,
                        target_field="optical_state",
                        rule="MAC table influencing optical power",
                        message="Optical physics diagnostics expose MAC-derived fields.",
                        severity=85,
                    )
                )
        return violations

    def _device_validation_state(
        self, device_id: str, violations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        layer_violations = [item for item in violations if item.get("device_id") == device_id]
        max_severity = max((int(item.get("severity") or 0) for item in layer_violations), default=0)
        return {
            "device_id": device_id,
            "layer_violations": layer_violations,
            "isolation_score": max(0, 100 - max_severity),
            "is_pure": len(layer_violations) == 0,
        }

    def _device_from_path(self, path: str) -> str | None:
        marker = "resolved_subscribers."
        if marker in path:
            tail = path.split(marker, 1)[1]
            return tail.split(".", 1)[0].split("[", 1)[0]
        marker = "devices."
        if marker in path:
            tail = path.split(marker, 1)[1]
            return tail.split(".", 1)[0].split("[", 1)[0]
        return None


def validate_layer_isolation(
    device_state: dict[str, Any], subscriber_model: dict[str, Any], optical_state: dict[str, Any]
) -> dict[str, Any]:
    return LayerValidationEngine().validate(device_state, subscriber_model, optical_state)


__all__ = ["LayerValidationEngine", "validate_layer_isolation"]