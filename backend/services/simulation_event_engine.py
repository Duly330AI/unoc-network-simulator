"""Deterministic event-log replay engine for debug projections.

The current production write paths still persist SQLModel rows directly. This
module provides a canonical, replayable simulation event stream derived from the
authoritative DB snapshot and projects physical, service, and analytics state
from that single stream for diagnostics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from backend.models import Device, Interface, Link
from backend.services.subscriber_model import PON_DEFAULT_CAPACITY, resolve_subscriber_model

SIMULATION_EVENT_TYPES = (
    "DEVICE_CREATED",
    "PORT_CONNECTED",
    "DEVICE_LINKED",
    "CPE_PROVISIONED",
    "ONT_ASSIGNED",
    "SERVICE_BOUND",
)


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    sequence: int
    type: str
    payload: dict[str, Any]
    source: str = "CANONICAL_DB_SNAPSHOT"

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "type": self.type,
            "payload": self.payload,
            "source": self.source,
        }


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _event(sequence: int, event_type: str, payload: dict[str, Any]) -> SimulationEvent:
    if event_type not in SIMULATION_EVENT_TYPES:
        raise ValueError(f"unsupported simulation event type: {event_type}")
    return SimulationEvent(sequence=sequence, type=event_type, payload=payload)


def build_simulation_event_log(session: Session) -> list[SimulationEvent]:
    devices = sorted(session.exec(select(Device)).all(), key=lambda item: item.id)
    interfaces = sorted(session.exec(select(Interface)).all(), key=lambda item: (item.device_id, item.name, item.id))
    links = sorted(session.exec(select(Link)).all(), key=lambda item: item.id)
    ifaces = {iface.id: iface for iface in interfaces}
    subscriber_model = resolve_subscriber_model(session)

    events: list[SimulationEvent] = []
    sequence = 0

    def append(event_type: str, payload: dict[str, Any]) -> None:
        nonlocal sequence
        events.append(_event(sequence, event_type, payload))
        sequence += 1

    for device in devices:
        append(
            "DEVICE_CREATED",
            {
                "device_id": device.id,
                "device_type": _value(device.type),
                "status": _value(device.status),
                "provisioned": bool(device.provisioned),
            },
        )

    for iface in interfaces:
        append(
            "PORT_CONNECTED",
            {
                "port_id": iface.id,
                "device_id": iface.device_id,
                "name": iface.name,
                "port_role": _value(iface.port_role),
                "capacity": iface.capacity,
            },
        )

    for link in links:
        a_iface = ifaces.get(link.a_interface_id)
        b_iface = ifaces.get(link.b_interface_id)
        append(
            "DEVICE_LINKED",
            {
                "link_id": link.id,
                "a_interface_id": link.a_interface_id,
                "b_interface_id": link.b_interface_id,
                "a_device_id": a_iface.device_id if a_iface else None,
                "b_device_id": b_iface.device_id if b_iface else None,
                "kind": _value(link.kind),
                "status": _value(link.status),
            },
        )

    for decision in sorted(
        subscriber_model.get("mapping_decisions", []), key=lambda item: str(item.get("subscriber_id"))
    ):
        subscriber_type = str(decision.get("subscriber_type") or "")
        if subscriber_type == "AON_CPE":
            append(
                "CPE_PROVISIONED",
                {
                    "subscriber_id": decision.get("subscriber_id"),
                    "subscriber_type": subscriber_type,
                    "anchor_device_id": decision.get("anchor_device_id"),
                    "anchor_interface_id": decision.get("anchor_interface_id"),
                    "counted": decision.get("counted"),
                    "reason": decision.get("reason"),
                },
            )
        elif subscriber_type in {"ONT", "BUSINESS_ONT"}:
            append(
                "ONT_ASSIGNED",
                {
                    "subscriber_id": decision.get("subscriber_id"),
                    "subscriber_type": subscriber_type,
                    "anchor_device_id": decision.get("anchor_device_id"),
                    "anchor_interface_id": decision.get("anchor_interface_id"),
                    "counted": decision.get("counted"),
                    "reason": decision.get("reason"),
                },
            )

        if decision.get("counted") is True:
            append(
                "SERVICE_BOUND",
                {
                    "subscriber_id": decision.get("subscriber_id"),
                    "subscriber_type": subscriber_type,
                    "domain": decision.get("domain"),
                    "anchor_device_id": decision.get("anchor_device_id"),
                    "anchor_interface_id": decision.get("anchor_interface_id"),
                    "source_event_sequence": sequence - 1,
                },
            )

    return events


def replay_simulation_events(events: list[SimulationEvent]) -> dict[str, Any]:
    physical = {"devices": {}, "ports": {}, "links": {}}
    service = {
        "ont_assignments": {},
        "cpe_provisioning": {},
        "service_bindings": [],
        "oversubscriptions": [],
    }
    analytics = {
        "device_counts": defaultdict(int),
        "olt_subscribers": defaultdict(int),
        "aon_subscribers": defaultdict(int),
        "pon_ports": defaultdict(lambda: {"effective_count": 0, "max_capacity": PON_DEFAULT_CAPACITY}),
    }
    traces: dict[str, list[int]] = defaultdict(list)

    for event in events:
        payload = event.payload
        if event.type == "DEVICE_CREATED":
            physical["devices"][payload["device_id"]] = payload
            analytics["device_counts"][payload.get("device_type") or "UNKNOWN"] += 1
            traces[payload["device_id"]].append(event.sequence)
        elif event.type == "PORT_CONNECTED":
            physical["ports"][payload["port_id"]] = payload
            traces[payload["device_id"]].append(event.sequence)
        elif event.type == "DEVICE_LINKED":
            physical["links"][payload["link_id"]] = payload
            for device_id in (payload.get("a_device_id"), payload.get("b_device_id")):
                if device_id:
                    traces[device_id].append(event.sequence)
        elif event.type == "ONT_ASSIGNED":
            service["ont_assignments"][payload["subscriber_id"]] = payload
            traces[payload["subscriber_id"]].append(event.sequence)
        elif event.type == "CPE_PROVISIONED":
            service["cpe_provisioning"][payload["subscriber_id"]] = payload
            traces[payload["subscriber_id"]].append(event.sequence)
            if payload.get("counted") is False:
                service["oversubscriptions"].append(payload)
        elif event.type == "SERVICE_BOUND":
            service["service_bindings"].append(payload)
            domain = payload.get("domain")
            if domain == "OLT":
                analytics["olt_subscribers"][payload["anchor_device_id"]] += 1
                analytics["pon_ports"][payload["anchor_interface_id"]]["effective_count"] += 1
            elif domain == "AON":
                analytics["aon_subscribers"][payload["anchor_device_id"]] += 1
            traces[payload["subscriber_id"]].append(event.sequence)
            if payload.get("anchor_device_id"):
                traces[payload["anchor_device_id"]].append(event.sequence)

    analytics_snapshot = {
        "device_counts": dict(sorted(analytics["device_counts"].items())),
        "olt_subscribers": dict(sorted(analytics["olt_subscribers"].items())),
        "aon_subscribers": dict(sorted(analytics["aon_subscribers"].items())),
        "pon_ports": {
            port_id: {
                **state,
                "utilization": state["effective_count"] / state["max_capacity"],
            }
            for port_id, state in sorted(analytics["pon_ports"].items())
        },
        "effective_subscriber_count": len(service["service_bindings"]),
    }
    return {
        "projection_source": "SIMULATION_EVENT_LOG_REPLAY",
        "event_count": len(events),
        "last_sequence": events[-1].sequence if events else None,
        "physical_projection": physical,
        "service_projection": service,
        "analytics_projection": analytics_snapshot,
        "event_traces": {key: value for key, value in sorted(traces.items())},
        "determinism": {
            "ordering": "sequence asc",
            "same_event_log_same_state": True,
            "projection_mutation": "projections are rebuilt from events, not mutated directly",
        },
    }


def serialize_events(events: list[SimulationEvent]) -> list[dict[str, Any]]:
    return [event.as_dict() for event in events]


__all__ = [
    "SIMULATION_EVENT_TYPES",
    "SimulationEvent",
    "build_simulation_event_log",
    "replay_simulation_events",
    "serialize_events",
]