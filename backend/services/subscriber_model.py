"""Canonical subscriber aggregation over the current topology graph."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any

from sqlmodel import Session, select

from backend.models import Device, DeviceType, Interface, Link, PortRole

ONT_TYPES = {"ONT", "BUSINESS_ONT"}
CPE_TYPES = {"AON_CPE"}
PASSIVE_TYPES = {"ODF", "NVT", "SPLITTER", "HOP"}
SUBSCRIBER_SOURCE = "L4_PROVISIONING_GRAPH"
PON_DEFAULT_CAPACITY = 128


def _type_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").upper()


def _port_role(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").upper()


def _is_provisioned(device: Device) -> bool:
    return bool(getattr(device, "provisioned", False))


def resolve_subscriber_model(session: Session) -> dict[str, Any]:
    devices = list(session.exec(select(Device)).all())
    interfaces = list(session.exec(select(Interface)).all())
    links = list(session.exec(select(Link)).all())

    devices_by_id = {device.id: device for device in devices}
    interfaces_by_id = {iface.id: iface for iface in interfaces}
    interfaces_by_device: dict[str, list[Interface]] = defaultdict(list)
    for iface in sorted(interfaces, key=lambda item: (item.device_id, item.name, item.id)):
        interfaces_by_device[iface.device_id].append(iface)

    link_neighbors: dict[str, set[str]] = defaultdict(set)
    for link in links:
        if link.a_interface_id and link.b_interface_id:
            link_neighbors[link.a_interface_id].add(link.b_interface_id)
            link_neighbors[link.b_interface_id].add(link.a_interface_id)

    raw_by_type = Counter(_type_name(device.type) for device in devices)
    provisioned_by_type = Counter(
        _type_name(device.type) for device in devices if _is_provisioned(device)
    )

    per_node: dict[str, dict[str, Any]] = {
        device.id: {
            "id": device.id,
            "type": _type_name(device.type),
            "subscribers": 0,
            "subscriber_ids": [],
            "subscriber_domain": None,
            "aggregation_source": SUBSCRIBER_SOURCE,
        }
        for device in devices
    }
    pon_occupancy: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    aon_access_occupancy: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    aon_port_candidates: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    decisions: list[dict[str, Any]] = []

    def sibling_ids(iface: Interface) -> list[str]:
        device = devices_by_id.get(iface.device_id)
        if not device:
            return []
        dev_type = _type_name(device.type)
        if dev_type not in PASSIVE_TYPES and dev_type not in ONT_TYPES and dev_type not in CPE_TYPES:
            return []
        return [other.id for other in interfaces_by_device.get(iface.device_id, []) if other.id != iface.id]

    def trace_anchor(start_device: Device, domain: str) -> tuple[str, str | None, str] | None:
        queue: deque[str] = deque(iface.id for iface in interfaces_by_device.get(start_device.id, []))
        visited: set[str] = set(queue)
        while queue:
            iface_id = queue.popleft()
            iface = interfaces_by_id.get(iface_id)
            if not iface:
                continue
            device = devices_by_id.get(iface.device_id)
            if not device:
                continue
            dev_type = _type_name(device.type)
            if domain == "OLT" and dev_type == "OLT" and _port_role(iface.port_role) == "PON":
                return device.id, iface.id, "first_reachable_olt_pon"
            if domain == "AON" and dev_type == "AON_SWITCH":
                return device.id, iface.id, "first_reachable_aon_switch"

            next_ids = sorted(link_neighbors.get(iface_id, set())) + sibling_ids(iface)
            for next_id in next_ids:
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append(next_id)
        return None

    def trace_direct_aon_anchor(start_device: Device) -> tuple[str, str | None, str] | None:
        for iface in interfaces_by_device.get(start_device.id, []):
            for peer_id in sorted(link_neighbors.get(iface.id, set())):
                peer_iface = interfaces_by_id.get(peer_id)
                if not peer_iface:
                    continue
                peer_device = devices_by_id.get(peer_iface.device_id)
                if peer_device and _type_name(peer_device.type) == "AON_SWITCH":
                    return peer_device.id, peer_iface.id, "direct_l4_cpe_access_port"
        return None

    for device in sorted(devices, key=lambda item: item.id):
        dev_type = _type_name(device.type)
        if dev_type not in ONT_TYPES and dev_type not in CPE_TYPES:
            continue
        if not _is_provisioned(device):
            decisions.append(
                {
                    "subscriber_id": device.id,
                    "subscriber_type": dev_type,
                    "counted": False,
                    "source": SUBSCRIBER_SOURCE,
                    "reason": "not_provisioned",
                }
            )
            continue

        leaf_domain = "OLT" if dev_type in ONT_TYPES else "AON"
        leaf_node = per_node[device.id]
        leaf_node["subscribers"] = 1
        leaf_node["subscriber_ids"] = [device.id]
        leaf_node["subscriber_domain"] = leaf_domain

        if leaf_domain == "AON":
            anchor = trace_direct_aon_anchor(device)
            if not anchor:
                decisions.append(
                    {
                        "subscriber_id": device.id,
                        "subscriber_type": dev_type,
                        "counted": False,
                        "domain": leaf_domain,
                        "source": SUBSCRIBER_SOURCE,
                        "reason": "no_direct_aon_access_port",
                    }
                )
                continue
            anchor_id, interface_id, reason = anchor
            if interface_id:
                aon_port_candidates[anchor_id][interface_id].append(device.id)
            decisions.append(
                {
                    "subscriber_id": device.id,
                    "subscriber_type": dev_type,
                    "counted": None,
                    "domain": leaf_domain,
                    "source": SUBSCRIBER_SOURCE,
                    "anchor_device_id": anchor_id,
                    "anchor_interface_id": interface_id,
                    "reason": reason,
                }
            )
            continue

        anchor = trace_anchor(device, leaf_domain)
        if not anchor:
            decisions.append(
                {
                    "subscriber_id": device.id,
                    "subscriber_type": dev_type,
                    "counted": False,
                    "domain": leaf_domain,
                    "source": SUBSCRIBER_SOURCE,
                    "reason": "no_reachable_anchor",
                }
            )
            continue

        anchor_id, interface_id, reason = anchor
        anchor_node = per_node[anchor_id]
        if device.id not in anchor_node["subscriber_ids"]:
            anchor_node["subscriber_ids"].append(device.id)
            anchor_node["subscriber_ids"].sort()
            anchor_node["subscribers"] = len(anchor_node["subscriber_ids"])
            anchor_node["subscriber_domain"] = leaf_domain

        if leaf_domain == "OLT" and interface_id:
            pon_occupancy[anchor_id][interface_id] += 1
        if leaf_domain == "AON" and interface_id:
            aon_access_occupancy[anchor_id][interface_id] += 1

        decisions.append(
            {
                "subscriber_id": device.id,
                "subscriber_type": dev_type,
                "counted": True,
                "domain": leaf_domain,
                "source": SUBSCRIBER_SOURCE,
                "anchor_device_id": anchor_id,
                "anchor_interface_id": interface_id,
                "reason": reason,
            }
        )

    for anchor_id, ports in sorted(aon_port_candidates.items()):
        anchor_node = per_node[anchor_id]
        for interface_id, cpe_ids in sorted(ports.items()):
            sorted_cpes = sorted(cpe_ids)
            counted_id = sorted_cpes[0]
            if counted_id not in anchor_node["subscriber_ids"]:
                anchor_node["subscriber_ids"].append(counted_id)
                anchor_node["subscriber_ids"].sort()
            anchor_node["subscriber_domain"] = "AON"
            aon_access_occupancy[anchor_id][interface_id] = 1

            for decision in decisions:
                if decision.get("domain") != "AON" or decision.get("anchor_interface_id") != interface_id:
                    continue
                if decision.get("subscriber_id") == counted_id:
                    decision["counted"] = True
                    decision["reason"] = "direct_l4_cpe_access_port_1_to_1"
                elif decision.get("subscriber_id") in sorted_cpes:
                    decision["counted"] = False
                    decision["reason"] = "aon_access_port_oversubscribed_1_to_1"

        anchor_node["subscribers"] = len(anchor_node["subscriber_ids"])

    olt_total = sum(
        node["subscribers"]
        for node in per_node.values()
        if node["subscriber_domain"] == "OLT" and node["type"] == "OLT"
    )
    aon_total = sum(
        node["subscribers"]
        for node in per_node.values()
        if node["subscriber_domain"] == "AON" and node["type"] == "AON_SWITCH"
    )

    return {
        "raw_device_counts": {
            "by_type": dict(sorted(raw_by_type.items())),
            "provisioned_by_type": dict(sorted(provisioned_by_type.items())),
        },
        "global": {
            "subscriber": {
                "total": olt_total + aon_total,
                "source": SUBSCRIBER_SOURCE,
                "provisioned_total": int(provisioned_by_type.get("ONT", 0))
                + int(provisioned_by_type.get("BUSINESS_ONT", 0))
                + int(provisioned_by_type.get("AON_CPE", 0)),
                "provisioned_olt_domain": int(provisioned_by_type.get("ONT", 0))
                + int(provisioned_by_type.get("BUSINESS_ONT", 0)),
                "provisioned_aon_domain": int(provisioned_by_type.get("AON_CPE", 0)),
                "olt_domain": olt_total,
                "aon_domain": aon_total,
                "resolved_olt_domain": olt_total,
                "resolved_aon_domain": aon_total,
                "resolved_total": olt_total + aon_total,
            }
        },
        "resolved_subscribers": per_node,
        "pon_occupancy": {
            device_id: dict(sorted(ports.items())) for device_id, ports in sorted(pon_occupancy.items())
        },
        "pon_ports": {
            device_id: {
                port_id: {
                    "provisioned_onts_count": count,
                    "max_capacity": PON_DEFAULT_CAPACITY,
                    "utilization": count / PON_DEFAULT_CAPACITY,
                    "source": SUBSCRIBER_SOURCE,
                }
                for port_id, count in sorted(ports.items())
            }
            for device_id, ports in sorted(pon_occupancy.items())
        },
        "aon_access_occupancy": {
            device_id: dict(sorted(ports.items()))
            for device_id, ports in sorted(aon_access_occupancy.items())
        },
        "aon_access_ports": {
            device_id: {
                port_id: {
                    "provisioned_cpes_count": count,
                    "max_capacity": 1,
                    "utilization": float(count),
                    "source": SUBSCRIBER_SOURCE,
                }
                for port_id, count in sorted(ports.items())
            }
            for device_id, ports in sorted(aon_access_occupancy.items())
        },
        "mapping_decisions": decisions,
    }


def subscriber_parameters(model: dict[str, Any], device_id: str) -> dict[str, Any]:
    node = model.get("resolved_subscribers", {}).get(device_id, {})
    return {
        "total": int(node.get("subscribers") or 0),
        "domain": node.get("subscriber_domain"),
        "subscriber_ids": list(node.get("subscriber_ids") or []),
    }


def pon_occupancy_for(model: dict[str, Any], device_id: str) -> dict[str, int]:
    return {str(k): int(v) for k, v in model.get("pon_occupancy", {}).get(device_id, {}).items()}


def aon_access_occupancy_for(model: dict[str, Any], device_id: str) -> dict[str, int]:
    return {
        str(k): int(v) for k, v in model.get("aon_access_occupancy", {}).get(device_id, {}).items()
    }


def pon_port_state_for(model: dict[str, Any], device_id: str) -> dict[str, dict[str, Any]]:
    return dict(model.get("pon_ports", {}).get(device_id, {}))


def aon_access_port_state_for(model: dict[str, Any], device_id: str) -> dict[str, dict[str, Any]]:
    return dict(model.get("aon_access_ports", {}).get(device_id, {}))