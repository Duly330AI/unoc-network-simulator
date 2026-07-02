"""Persistent append-only EventStore primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from backend.models import EventStoreRecord

DOMAIN_EVENT_TYPES = {
    "DEVICE_CREATED",
    "DEVICE_CONNECTED",
    "DEVICE_DELETED",
    "DEVICE_LINKED",
    "DEVICE_UPDATED",
    "PORT_CONNECTED",
    "CPE_PROVISIONED",
    "ONT_ASSIGNED",
    "SERVICE_BOUND",
    "DEVICE_PROVISIONED",
    "LINK_CREATED",
    "LINK_DELETED",
    "LINK_UPDATED",
    "PROVISIONING_UPDATED",
    "RUNTIME_EVENT",
}


def _next_sequence(session: Session) -> int:
    current = session.exec(
        select(EventStoreRecord.sequence).order_by(EventStoreRecord.sequence.desc()).limit(1)
    ).first()
    return int(-1 if current is None else current) + 1


def append_event(
    session: Session,
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "EVENT_STORE",
    correlation_id: str | None = None,
) -> EventStoreRecord:
    if event_type not in DOMAIN_EVENT_TYPES:
        event_type = "RUNTIME_EVENT"
    record = EventStoreRecord(
        sequence=_next_sequence(session),
        event_type=event_type,
        payload=payload,
        source=source,
        created_at=datetime.now(UTC).isoformat(),
        correlation_id=correlation_id,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def append_runtime_event(event: Any) -> None:
    try:
        from backend.db import get_session, init_db

        init_db()
        event_type = str(getattr(event, "type", "RUNTIME_EVENT")).upper().replace(".", "_")
        payload = dict(getattr(event, "payload", {}) or {})
        with get_session() as session:
            append_event(
                session,
                event_type,
                payload,
                source="RUNTIME_EVENT_BUS",
                correlation_id=getattr(event, "correlation_id", None),
            )
    except Exception:
        return None


def append_write_path_event(
    session: Session,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    data = dict(payload or {})
    data.setdefault("entity_id", entity_id)
    data.setdefault("timestamp", datetime.now(UTC).isoformat())
    try:
        append_event(session, event_type, data, source="WRITE_PATH")
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass


def event_store_snapshot(session: Session) -> dict[str, Any]:
    rows = session.exec(select(EventStoreRecord).order_by(EventStoreRecord.sequence)).all()
    return {
        "total_events": len(rows),
        "last_event_timestamp": rows[-1].created_at if rows else None,
        "last_sequence": rows[-1].sequence if rows else None,
        "events": [row.model_dump() for row in rows],
    }


__all__ = [
    "DOMAIN_EVENT_TYPES",
    "append_event",
    "append_runtime_event",
    "append_write_path_event",
    "event_store_snapshot",
]