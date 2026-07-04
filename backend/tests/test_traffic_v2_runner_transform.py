import logging

from backend.services.traffic import v2_engine
from backend.services.traffic.v2_runner import (
    TariffTrafficRunner,
    build_device_metric_changes,
    build_link_metric_changes,
    transform_go_snapshot_to_frontend,
)


class _StopAfterOneLoop:
    def is_set(self):
        return False

    def wait(self, _timeout):
        return True


class _FakeGoClient:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def tick(self):
        return {}

    def snapshot(self):
        return self._snapshot


def _runner_for_snapshot(snapshot):
    runner = TariffTrafficRunner.__new__(TariffTrafficRunner)
    runner.use_go = True
    runner._go_client = _FakeGoClient(snapshot)
    runner.engine = None
    runner._stop = _StopAfterOneLoop()
    runner.interval = 0.0
    runner._log = logging.getLogger("test.traffic.v2_runner")
    return runner


def test_transform_go_snapshot_preserves_congestion_and_capacity_fields():
    go_snapshot = {
        "tick": 12,
        "device_metrics": {
            "edge1": {
                "up_mbps": 900.0,
                "down_mbps": 950.0,
                "up_bps": 900_000_000.0,
                "down_bps": 950_000_000.0,
                "utilization": 0.95,
                "capacity_mbps": 1000.0,
                "congested": True,
            }
        },
        "link_metrics": {
            "l1": {
                "traffic_mbps": 950.0,
                "up_bps": 100_000_000.0,
                "down_bps": 950_000_000.0,
                "utilization": 0.95,
                "capacity_mbps": 1000.0,
                "congested": True,
            }
        },
    }

    frontend = transform_go_snapshot_to_frontend(go_snapshot)

    assert frontend["lastTick"] == 12
    assert frontend["devices"]["edge1"]["capacity_mbps"] == 1000.0
    assert frontend["devices"]["edge1"]["congested"] is True
    assert frontend["links"]["l1"]["capacity_mbps"] == 1000.0
    assert frontend["links"]["l1"]["congested"] is True


def test_go_snapshot_ws_change_helpers_preserve_congestion_and_capacity_fields():
    go_snapshot = {
        "device_metrics": {
            "edge1": {
                "up_bps": 100.0,
                "down_bps": 200.0,
                "utilization": 0.2,
                "capacity_mbps": 1000.0,
                "congested": False,
            }
        },
        "link_metrics": {
            "l1": {
                "up_bps": 100.0,
                "down_bps": 200.0,
                "utilization": 0.2,
                "capacity_mbps": 1000.0,
                "congested": False,
            }
        },
    }

    device_changes = build_device_metric_changes(go_snapshot)
    link_changes = build_link_metric_changes(go_snapshot)

    assert device_changes == [
        {
            "id": "edge1",
            "bps": 300.0,
            "upstream_bps": 100.0,
            "downstream_bps": 200.0,
            "utilization": 0.2,
            "capacity_mbps": 1000.0,
            "congested": False,
        }
    ]
    assert link_changes == [
        {
            "id": "l1",
            "bps": 300.0,
            "utilization": 0.2,
            "capacity_mbps": 1000.0,
            "congested": False,
        }
    ]


def test_run_loop_publishes_empty_metric_events_for_empty_go_snapshot(monkeypatch):
    published = []
    monkeypatch.setattr("backend.events.publish", lambda event: published.append(event))
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", None)
    monkeypatch.setattr(v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", None)

    runner = _runner_for_snapshot({"tick": 42, "device_metrics": {}, "link_metrics": {}})
    runner._run_loop()

    assert [event.type for event in published] == [
        "deviceMetricsUpdated",
        "linkMetricsUpdated",
    ]
    assert published[0].payload == {"devices": [], "tick": 42, "authoritative": True}
    assert published[1].payload == {"links": [], "tick": 42, "authoritative": True}


def test_run_loop_skips_metric_events_when_go_snapshot_missing(monkeypatch):
    published = []
    monkeypatch.setattr("backend.events.publish", lambda event: published.append(event))
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", None)

    runner = _runner_for_snapshot(None)
    runner._run_loop()

    assert published == []
