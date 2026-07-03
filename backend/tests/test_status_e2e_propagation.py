from fastapi.testclient import TestClient

from backend.db import get_session, init_db, reset_db
from backend.main import app
from backend.models import Device, DeviceType, Interface, Link, LinkType, Status
from backend.services.event_store_runtime import projection_write_context
from backend.services.provisioning_service import provision_device
from backend.services.status_recompute import recompute_devices_status


def _client() -> TestClient:
    return TestClient(app)


def setup_function(_):
    reset_db()
    init_db()


def _dev(i, t):
    return Device(id=i, name=i, type=t)


def _iface(device: Device, name: str = "if0"):
    return Interface(id=f"{device.id}-{name}", device_id=device.id, name=name)


def _link(a: Device, b: Device, kind: LinkType = LinkType.FIBER):
    return Link(
        id=f"{a.id}-{b.id}",
        a_interface_id=f"{a.id}-if0",
        b_interface_id=f"{b.id}-if0",
        kind=kind,
    )


def test_failure_recovery_snapshot_and_api(monkeypatch):
    # Enable dev features for snapshot and propagation for status
    monkeypatch.setenv("UNOC_DEV_FEATURES", "1")

    with projection_write_context(), get_session() as s:
        bb = _dev("bb1", DeviceType.BACKBONE_GATEWAY)
        core = _dev("core1x", DeviceType.CORE_ROUTER)
        edge = _dev("edge1x", DeviceType.EDGE_ROUTER)
        s.add(bb)
        s.add(core)
        s.add(edge)
        for dev in (bb, core, edge):
            if dev.type != DeviceType.BACKBONE_GATEWAY or True:
                s.add(_iface(dev))
        s.add(_link(bb, core))
        s.add(_link(core, edge))
        s.commit()
        provision_device(s, core)
        provision_device(s, edge)
        s.commit()

        # Baseline recompute
        recompute_devices_status(s, include_passive_propagation=True)

    c = _client()
    r = c.get("/api/debug/full-snapshot", params={"sections": "devices"})
    assert r.status_code == 200
    body = r.json()
    devs = {d["id"]: d for d in body["devices"]}
    assert devs["bb1"]["effective_status"] == "UP"
    # With always-on auto L3 uplink configuration, core and edge should be UP after provisioning
    assert devs["core1x"]["effective_status"] == "UP"
    assert devs["edge1x"]["effective_status"] == "UP"

    # Fail the backbone and recompute
    with projection_write_context(), get_session() as s:
        bb = s.get(Device, "bb1")
        assert bb is not None
        bb.admin_override_status = Status.DOWN
        s.add(bb)
        s.commit()
        recompute_devices_status(s, include_passive_propagation=True)

    r = c.get("/api/debug/full-snapshot", params={"sections": "devices"})
    body = r.json()
    devs = {d["id"]: d for d in body["devices"]}
    assert devs["bb1"]["effective_status"] == "DOWN"
    # Core and edge lose reachability to the anchor and degrade to DOWN
    assert devs["core1x"]["effective_status"] == "DOWN"
    assert devs["edge1x"]["effective_status"] == "DOWN"

    # Recover the backbone and recompute
    with projection_write_context(), get_session() as s:
        bb = s.get(Device, "bb1")
        assert bb is not None
        bb.admin_override_status = None
        s.add(bb)
        s.commit()
        recompute_devices_status(s, include_passive_propagation=True)

    r = c.get("/api/debug/full-snapshot", params={"sections": "devices"})
    body = r.json()
    devs = {d["id"]: d for d in body["devices"]}
    assert devs["bb1"]["effective_status"] == "UP"
    # With backbone recovered, auto L3 reachability is restored → core and edge return to UP
    assert devs["core1x"]["effective_status"] == "UP"
    assert devs["edge1x"]["effective_status"] == "UP"


def test_recompute_devices_status_persists_transition_to_database():
    with projection_write_context(), get_session() as s:
        device = Device(
            id="status_persist_ont",
            name="status_persist_ont",
            type=DeviceType.ONT,
            status=Status.UP,
            provisioned=False,
        )
        s.add(device)
        s.commit()

        transitions = recompute_devices_status(
            s,
            device_ids=[device.id],
            baseline_status={device.id: Status.UP},
        )

    assert transitions == [("status_persist_ont", "Status.UP", "Status.DOWN")]

    with get_session() as s:
        stored = s.get(Device, "status_persist_ont")
        assert stored is not None
        assert stored.status == Status.DOWN
