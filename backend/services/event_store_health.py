"""EventStore migration/backfill health diagnostics."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from backend.models import EventStoreRecord
from backend.services.event_store import append_event, event_store_snapshot
from backend.services.event_store_runtime import event_store_enforcement_enabled
from backend.services.simulation_event_engine import (
    SIMULATION_EVENT_TYPES,
    SimulationEvent,
    build_simulation_event_log,
    replay_simulation_events,
)

BACKFILL_SOURCE = "BACKFILL_DB_SNAPSHOT"


def ensure_backfilled_event_store(session: Session) -> int:
    existing = session.exec(
        select(EventStoreRecord.id).where(EventStoreRecord.source == BACKFILL_SOURCE)
    ).first()
    if existing is not None:
        return 0
    count = 0
    for event in build_simulation_event_log(session):
        append_event(session, event.type, event.payload, source=BACKFILL_SOURCE)
        count += 1
    return count


def _records_to_simulation_events(records: list[EventStoreRecord]) -> list[SimulationEvent]:
    events: list[SimulationEvent] = []
    sequence = 0
    for record in records:
        if record.source != BACKFILL_SOURCE:
            continue
        if record.event_type not in SIMULATION_EVENT_TYPES:
            continue
        events.append(
            SimulationEvent(
                sequence=sequence,
                type=record.event_type,
                payload=dict(record.payload or {}),
                source=record.source,
            )
        )
        sequence += 1
    return events


def build_event_store_health(session: Session) -> dict[str, Any]:
    backfilled = ensure_backfilled_event_store(session)
    snapshot = event_store_snapshot(session)
    records = session.exec(select(EventStoreRecord).order_by(EventStoreRecord.sequence)).all()
    replayable_events = _records_to_simulation_events(records)
    projections = replay_simulation_events(replayable_events)
    backfill_count = sum(1 for record in records if record.source == BACKFILL_SOURCE)
    projection_lag = len(replayable_events) - int(projections.get("event_count") or 0)
    legacy_runtime_events = [record for record in records if record.source == "RUNTIME_EVENT_BUS"]
    write_path_events = [record for record in records if record.source == "WRITE_PATH"]
    consistency = "ok"
    if projection_lag != 0:
        consistency = "projection_lag"
    elif not event_store_enforcement_enabled():
        consistency = "migration_incomplete_enforcement_disabled"

    return {
        "total_events": snapshot["total_events"],
        "last_event_timestamp": snapshot["last_event_timestamp"],
        "last_sequence": snapshot["last_sequence"],
        "backfill_migration": {
            "source": BACKFILL_SOURCE,
            "events_added_this_call": backfilled,
            "backfilled_events_total": backfill_count,
        },
        "projection_lag": projection_lag,
        "consistency_status": consistency,
        "event_store_enforcement": {
            "enabled": event_store_enforcement_enabled(),
            "bypass_error": "EVENT_STORE_BYPASS",
            "guarded_models": ["Device", "Interface", "Link", "ProvisioningRecord"],
        },
        "projection_summary": {
            "event_count": projections.get("event_count"),
            "effective_subscriber_count": projections.get("analytics_projection", {}).get(
                "effective_subscriber_count"
            ),
            "olt_subscribers": projections.get("analytics_projection", {}).get("olt_subscribers", {}),
            "aon_subscribers": projections.get("analytics_projection", {}).get("aon_subscribers", {}),
        },
        "legacy_runtime_events_recorded": len(legacy_runtime_events),
        "write_path_events_recorded": len(write_path_events),
        "hard_rule_status": (
            "enforced" if event_store_enforcement_enabled() else "available_but_not_enabled"
        ),
    }


__all__ = ["BACKFILL_SOURCE", "build_event_store_health", "ensure_backfilled_event_store"]