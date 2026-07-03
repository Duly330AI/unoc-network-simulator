import json

from fastapi.testclient import TestClient

from backend import events
from backend.api.endpoints.devices_helpers_query import (
    bump_devices_cache_epoch,
    get_devices_json_cached,
)
from backend.db import get_session, init_db, reset_db
from backend.main import app
from backend.models import Device, DeviceType, Interface, Link, Status
from backend.services.event_store_runtime import projection_write_context

client = TestClient(app)


def _add_device(session, dev_id: str, dev_type: DeviceType, **kwargs) -> Device:
    device = Device(
        id=dev_id,
        name=dev_id,
        type=dev_type,
        status=kwargs.pop("status", Status.DOWN),
        provisioned=kwargs.pop("provisioned", True),
        **kwargs,
    )
    session.add(device)
    session.add(Interface(id=f"{dev_id}-if0", device_id=dev_id, name="if0"))
    return device


def test_link_length_update_triggers_real_optical_recompute(monkeypatch):
    reset_db()
    init_db()
    events.reset_events()
    bump_devices_cache_epoch("test_start")

    with projection_write_context(), get_session() as session:
        _add_device(session, "rx_olt", DeviceType.OLT)
        _add_device(session, "rx_ont", DeviceType.ONT)
        session.add(
            Link(
                id="rx_link",
                a_interface_id="rx_olt-if0",
                b_interface_id="rx_ont-if0",
                status=Status.UP,
                length_km=5.0,
            )
        )
        session.commit()

    calls: list[set[str] | None] = []

    def fake_recompute(*, device_ids=None, link_ids=None):
        calls.append(set(link_ids or []))

    monkeypatch.setattr(
        "backend.services.optical_service.recompute_optical_paths_for_affected_onts",
        fake_recompute,
    )
    monkeypatch.setattr("backend.api.endpoints.links_helpers_update.get_status_client", lambda: None)
    monkeypatch.setattr("backend.services.recompute_coalescer.schedule", lambda **_kwargs: None)

    response = client.put("/api/links/rx_link", json={"length_km": 500.0})

    assert response.status_code == 200, response.text
    assert calls == [{"rx_link"}]
    assert not any(
        event.type == "device.optical.updated" and "affected_link_ids" in event.payload
        for event in events.get_event_history()
    )


def test_optical_updated_event_payload_has_id_and_both_field_families(monkeypatch):
    reset_db()
    init_db()
    events.reset_events()
    bump_devices_cache_epoch("test_start")

    with projection_write_context(), get_session() as session:
        _add_device(
            session,
            "evt_olt",
            DeviceType.OLT,
            status=Status.UP,
            provisioned=True,
            tx_power_dbm=4.0,
        )
        _add_device(
            session,
            "evt_ont",
            DeviceType.ONT,
            status=Status.UP,
            provisioned=True,
            sensitivity_min_dbm=-28.0,
        )
        session.commit()

    class FakeOpticalClient:
        def get_path(self, ont_id: str):
            assert ont_id == "evt_ont"
            return {
                "path_exists": True,
                "olt_id": "evt_olt",
                "total_attenuation_db": 8.5,
            }

    monkeypatch.setattr(
        "backend.services.optical_service.get_optical_client",
        lambda: FakeOpticalClient(),
    )

    from backend.services.optical_service import recompute_optical_paths_for_affected_onts

    recompute_optical_paths_for_affected_onts(device_ids={"evt_ont"})

    optical_events = [
        event for event in events.get_event_history() if event.type == "device.optical.updated"
    ]
    assert optical_events
    payload = optical_events[-1].payload
    assert payload["id"] == "evt_ont"
    assert payload["signal_power_dbm"] == payload["received_dbm"]
    assert payload["signal_margin_db"] == payload["margin_db"]
    assert payload["signal_status"] == "OK"
    assert payload["attenuation_db"] == 8.5
    assert payload["total_path_attenuation_db"] == 8.5


def test_devices_cache_epoch_refreshes_json_after_signal_only_change():
    reset_db()
    init_db()
    bump_devices_cache_epoch("test_start")

    with projection_write_context(), get_session() as session:
        _add_device(
            session,
            "cache_ont",
            DeviceType.ONT,
            status=Status.UP,
            provisioned=True,
            signal_power_dbm=-10.0,
            signal_margin_db=18.0,
        )
        session.commit()

    with get_session() as session:
        first_payload, first_etag = get_devices_json_cached(session, include_interfaces=False)
    assert next(d for d in json.loads(first_payload) if d["id"] == "cache_ont")[
        "signal_power_dbm"
    ] == -10.0

    with projection_write_context(), get_session() as session:
        ont = session.get(Device, "cache_ont")
        assert ont is not None
        ont.signal_power_dbm = -42.0
        session.add(ont)
        session.commit()

    with get_session() as session:
        stale_payload, stale_etag = get_devices_json_cached(session, include_interfaces=False)
    assert stale_etag == first_etag
    assert next(d for d in json.loads(stale_payload) if d["id"] == "cache_ont")[
        "signal_power_dbm"
    ] == -10.0

    bump_devices_cache_epoch("test_signal_change")

    with get_session() as session:
        fresh_payload, fresh_etag = get_devices_json_cached(session, include_interfaces=False)
    assert fresh_etag != first_etag
    assert next(d for d in json.loads(fresh_payload) if d["id"] == "cache_ont")[
        "signal_power_dbm"
    ] == -42.0


def test_bulk_status_update_invalidates_devices_cache_when_status_changes(monkeypatch):
    reset_db()
    init_db()

    with projection_write_context(), get_session() as session:
        _add_device(
            session,
            "status_core",
            DeviceType.CORE_ROUTER,
            status=Status.DOWN,
            provisioned=True,
        )
        session.commit()

    bumps: list[str | None] = []
    monkeypatch.setattr(
        "backend.api.endpoints.devices_helpers_query.bump_devices_cache_epoch",
        lambda reason=None: bumps.append(reason) or len(bumps),
    )
    monkeypatch.setattr("backend.services.status_service.evaluate_device_status", lambda _d: Status.UP)

    from backend.services.status_service import bulk_update_device_statuses

    bulk_update_device_statuses(["status_core"])

    assert bumps == ["status_bulk_update"]
    with get_session() as session:
        device = session.get(Device, "status_core")
        assert device is not None
        assert device.status == Status.UP
