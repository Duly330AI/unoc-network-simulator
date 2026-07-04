from fastapi import BackgroundTasks
from sqlmodel import Session

from backend.api.endpoints import provisioning
from backend.db import engine, init_db, reset_db
from backend.models import Device, DeviceType
from backend.services.event_store_runtime import projection_write_context


def setup_function(_):
    reset_db()
    init_db()


def test_provision_endpoint_persists_recomputed_status_with_status_client(monkeypatch):
    with projection_write_context():
        with Session(engine) as s:
            s.add(
                Device(id="prov_core_status", name="prov_core_status", type=DeviceType.CORE_ROUTER)
            )
            s.commit()

    calls = []

    class FakeStatusClient:
        def propagate_status(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(provisioning, "get_status_client", lambda: FakeStatusClient())
    monkeypatch.setattr(provisioning.coalescer, "schedule", lambda **_: None)
    monkeypatch.setattr(provisioning, "schedule", lambda *_, **__: None)

    with projection_write_context():
        provisioning._provision_device_guarded("prov_core_status", BackgroundTasks())

    assert calls == [
        {
            "changed_device_ids": ["prov_core_status"],
            "changed_link_ids": [],
            "update_database": True,
        }
    ]
