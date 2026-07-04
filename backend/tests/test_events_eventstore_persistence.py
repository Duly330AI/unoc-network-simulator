from sqlmodel import select

from backend import events
from backend.db import get_session
from backend.models import EventStoreRecord


def _event_store_records() -> list[EventStoreRecord]:
    with get_session() as session:
        return session.exec(select(EventStoreRecord).order_by(EventStoreRecord.sequence)).all()


def test_publish_skips_eventstore_for_ephemeral_metrics_events():
    events.reset_events()

    events.publish(
        events.Event(type="deviceMetricsUpdated", payload={"devices": [], "tick": 123})
    )

    assert [event.type for event in events.get_event_history()] == ["deviceMetricsUpdated"]
    assert _event_store_records() == []


def test_publish_persists_non_telemetry_runtime_events():
    events.reset_events()

    events.publish(
        events.Event(type="device.status.changed", payload={"id": "dev1", "status": "DOWN"})
    )

    records = _event_store_records()
    assert len(records) == 1
    assert records[0].source == "RUNTIME_EVENT_BUS"
    assert records[0].payload == {"id": "dev1", "status": "DOWN"}
