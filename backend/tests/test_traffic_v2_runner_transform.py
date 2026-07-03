from backend.services.traffic.v2_runner import (
    build_device_metric_changes,
    build_link_metric_changes,
    transform_go_snapshot_to_frontend,
)


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
