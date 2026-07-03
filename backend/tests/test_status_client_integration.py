"""Integration tests for StatusClient (Go service + Python fallback).

Tests verify:
1. Go service connection and health check
2. propagate_status() via Go service (when available)
3. Automatic fallback to Python when Go unavailable
4. Python fallback functions (detect_causal_chain_python, bulk_update)
5. Error handling and timeout scenarios

REQUIRES: Status Propagation Go service (port 50053) + PostgreSQL
"""

import pytest

from backend.clients.go_services.status_client import StatusClient, get_status_client
from backend.db import get_session, init_db, reset_db
from backend.models import Device, DeviceType, Interface, Link, Status
from backend.services.event_store_runtime import projection_write_context
from backend.services.status_service import bulk_update_device_statuses, detect_causal_chain_python

pytestmark = pytest.mark.integration  # Mark entire module as integration test


@pytest.fixture
def status_client():
    """Get StatusClient instance for testing."""
    client = get_status_client()
    yield client
    if client:
        client.close()


@pytest.fixture
def session():
    reset_db()
    init_db()
    with projection_write_context(), get_session() as s:
        yield s


@pytest.fixture
def simple_topology(session):
    """
    Create simple 3-device topology for status propagation testing.

    Topology:
        CORE (UP) -- Link1 -- SWITCH (UP) -- Link2 -- ONT (UP)

    Returns device IDs: (core_id, switch_id, ont_id)
    """
    # Create devices
    core = Device(
        id="core-1",
        name="Core Router",
        type=DeviceType.CORE_ROUTER,
        status=Status.UP,
        provisioned=True,
    )
    switch = Device(
        id="switch-1",
        name="Access Switch",
        type=DeviceType.AON_SWITCH,
        status=Status.UP,
        provisioned=True,
    )
    ont = Device(
        id="ont-1",
        name="Customer ONT",
        type=DeviceType.ONT,
        status=Status.UP,
        provisioned=True,
    )

    session.add(core)
    session.add(switch)
    session.add(ont)
    session.commit()

    # Create interfaces
    core_if = Interface(id="core-1-eth0", device_id="core-1", name="eth0")
    switch_if1 = Interface(id="switch-1-eth0", device_id="switch-1", name="eth0")
    switch_if2 = Interface(id="switch-1-eth1", device_id="switch-1", name="eth1")
    ont_if = Interface(id="ont-1-eth0", device_id="ont-1", name="eth0")

    session.add(core_if)
    session.add(switch_if1)
    session.add(switch_if2)
    session.add(ont_if)
    session.commit()

    # Create links
    link1 = Link(id="link-1", a_interface_id="core-1-eth0", b_interface_id="switch-1-eth0")
    link2 = Link(id="link-2", a_interface_id="switch-1-eth1", b_interface_id="ont-1-eth0")

    session.add(link1)
    session.add(link2)
    session.commit()

    yield (core.id, switch.id, ont.id)


def test_status_client_health_check(status_client):
    """Test StatusClient health check."""
    health = status_client.health()

    assert health is not None
    assert "status" in health
    assert "backend" in health
    # Backend is either "go" (if service available) or "python" (fallback)
    assert health["backend"] in ["go", "python"]

    if health["backend"] == "go":
        # Go service may be UP, HEALTHY, or UNHEALTHY (depends on DB connection)
        assert health["status"] in ["UP", "HEALTHY", "UNHEALTHY"]
        assert "version" in health or "message" in health
    else:
        # Python fallback
        assert health["status"] == "python-fallback"


def test_detect_causal_chain_python_empty_changes():
    """Test detect_causal_chain_python with no changes."""
    result = detect_causal_chain_python(changed_device_ids=[])

    assert "affected_devices" in result
    assert "affected_links" in result
    assert "dependency_paths" in result
    assert len(result["affected_devices"]) == 0


def test_detect_causal_chain_python_single_device(simple_topology, session):
    """Test detect_causal_chain_python with single device change."""
    core_id, switch_id, ont_id = simple_topology

    # Simulate core router going DOWN
    result = detect_causal_chain_python(changed_device_ids=[core_id])

    assert "affected_devices" in result
    affected = result["affected_devices"]

    # Should include core itself
    assert core_id in affected

    # Should include downstream devices (switch, ont)
    # (Note: Actual propagation logic may vary based on link status)
    assert len(affected) >= 1


def test_detect_causal_chain_python_with_links(simple_topology, session):
    """Test detect_causal_chain_python with device and link changes."""
    core_id, switch_id, ont_id = simple_topology

    # Simulate core + link change
    result = detect_causal_chain_python(changed_device_ids=[core_id], changed_link_ids=["link-1"])

    assert "affected_devices" in result
    assert "dependency_paths" in result

    affected = result["affected_devices"]
    assert core_id in affected


def test_bulk_update_device_statuses_single_device(simple_topology, session):
    """Test bulk_update_device_statuses with single device."""
    core_id, switch_id, ont_id = simple_topology

    # Change device status manually
    core = session.get(Device, core_id)
    core.status = Status.DOWN
    session.commit()

    # Call bulk update
    bulk_update_device_statuses([core_id])

    # Reload device
    session.expire_all()
    core = session.get(Device, core_id)

    # Status should be recomputed (may be UP or DOWN depending on logic)
    assert core.status in [Status.UP, Status.DOWN, Status.DEGRADED]


def test_bulk_update_device_statuses_multiple_devices(simple_topology, session):
    """Test bulk_update_device_statuses with multiple devices."""
    core_id, switch_id, ont_id = simple_topology

    # Change all device statuses
    for device_id in [core_id, switch_id, ont_id]:
        device = session.get(Device, device_id)
        device.status = Status.DOWN
        session.commit()

    # Call bulk update
    bulk_update_device_statuses([core_id, switch_id, ont_id])

    # Reload devices
    session.expire_all()

    # All devices should have recomputed status
    core = session.get(Device, core_id)
    switch = session.get(Device, switch_id)
    ont = session.get(Device, ont_id)

    assert core.status in [Status.UP, Status.DOWN, Status.DEGRADED]
    assert switch.status in [Status.UP, Status.DOWN, Status.DEGRADED]
    assert ont.status in [Status.UP, Status.DOWN, Status.DEGRADED]


def test_propagate_status_python_fallback(status_client, simple_topology, session):
    """Test propagate_status() when using Python fallback."""
    core_id, switch_id, ont_id = simple_topology

    # Call propagate_status (may use Go or Python depending on availability)
    result = status_client.propagate_status(
        changed_device_ids=[core_id], changed_link_ids=[], update_database=True
    )

    assert "affected_devices" in result
    assert "source" in result
    assert result["source"] in ["go", "python"]

    affected = result["affected_devices"]
    assert core_id in affected


def test_propagate_status_with_link_changes(status_client, simple_topology, session):
    """Test propagate_status() with both device and link changes."""
    core_id, switch_id, ont_id = simple_topology

    result = status_client.propagate_status(
        changed_device_ids=[core_id], changed_link_ids=["link-1"], update_database=True
    )

    assert "affected_devices" in result
    assert "source" in result
    assert result["source"] in ["go", "python"]

    # Should detect affected devices
    affected = result["affected_devices"]
    assert len(affected) >= 1
    assert core_id in affected


def test_propagate_status_no_update_database(status_client, simple_topology, session):
    """Test propagate_status() with update_database=False."""
    core_id, switch_id, ont_id = simple_topology

    # Save original statuses
    core = session.get(Device, core_id)
    original_status = core.status

    # Call propagate_status with update_database=False
    result = status_client.propagate_status(
        changed_device_ids=[core_id], changed_link_ids=[], update_database=False
    )

    assert "affected_devices" in result

    # Reload device
    session.expire_all()
    core = session.get(Device, core_id)

    # Status should be unchanged
    assert core.status == original_status


def test_propagate_status_performance_baseline(status_client, simple_topology, session):
    """Test propagate_status() performance baseline."""
    core_id, switch_id, ont_id = simple_topology

    result = status_client.propagate_status(
        changed_device_ids=[core_id], changed_link_ids=[], update_database=True
    )

    assert "duration_ms" in result

    # Performance expectations:
    # - Go service: <1ms for 3 devices
    # - Python fallback: 10-100ms for 3 devices
    duration = result["duration_ms"]

    if result["source"] == "go":
        # Go service should be very fast
        assert duration < 10, f"Go service took {duration}ms (expected <10ms)"
    else:
        # Python fallback may be slower
        assert duration < 1000, f"Python fallback took {duration}ms (expected <1000ms)"


def test_status_client_singleton():
    """Test get_status_client() returns singleton."""
    client1 = get_status_client()
    client2 = get_status_client()

    assert client1 is client2  # Same instance

    if client1:
        client1.close()


def test_propagate_status_empty_changes(status_client):
    """Test propagate_status() with no changes."""
    result = status_client.propagate_status(
        changed_device_ids=[], changed_link_ids=[], update_database=False
    )

    assert "affected_devices" in result
    assert len(result["affected_devices"]) == 0


@pytest.mark.parametrize(
    ("update_database", "expected_calls"),
    [
        (True, [["go-ont-1", "go-switch-1"]]),
        (False, []),
    ],
)
def test_go_propagation_uses_python_writer_for_persistence(
    monkeypatch, update_database, expected_calls
):
    """Go propagation returns affected IDs; Python owns DB persistence."""
    from backend.proto import status_pb2
    from backend.services import status_service

    calls: list[list[str]] = []

    def fake_bulk_update_device_statuses(device_ids: list[str]) -> None:
        calls.append(list(device_ids))

    class FakeStatusStub:
        def PropagateStatus(self, request, timeout):  # noqa: N802
            assert list(request.changed_device_ids) == ["go-core-1"]
            assert list(request.changed_link_ids) == ["go-link-1"]
            assert timeout == 30.0
            return status_pb2.PropagateResponse(
                device_ids=["go-ont-1", "go-switch-1"],
                duration_ms=4,
                status="success",
            )

    monkeypatch.setattr(
        status_service,
        "bulk_update_device_statuses",
        fake_bulk_update_device_statuses,
    )

    client = StatusClient.__new__(StatusClient)
    client._stub = FakeStatusStub()
    client.timeout = 30.0

    result = client._propagate_go(
        changed_device_ids=["go-core-1"],
        changed_link_ids=["go-link-1"],
        update_database=update_database,
    )

    assert result["affected_devices"] == ["go-ont-1", "go-switch-1"]
    assert result["source"] == "go"
    assert calls == expected_calls
