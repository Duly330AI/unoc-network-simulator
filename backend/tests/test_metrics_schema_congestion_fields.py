from backend.api.schemas import MetricsSnapshotResponse


def test_metrics_snapshot_response_retains_congestion_capacity_fields():
    response = MetricsSnapshotResponse.model_validate(
        {
            "lastTick": 3,
            "devices": {
                "edge1": {
                    "bps": 950_000_000.0,
                    "utilization": 0.95,
                    "capacity_mbps": 1000.0,
                    "congested": True,
                }
            },
            "links": {
                "l1": {
                    "bps": 950_000_000.0,
                    "utilization": 0.95,
                    "capacity_mbps": 1000.0,
                    "congested": True,
                }
            },
        }
    )

    dumped = response.model_dump()

    assert dumped["devices"]["edge1"]["capacity_mbps"] == 1000.0
    assert dumped["devices"]["edge1"]["congested"] is True
    assert dumped["links"]["l1"]["capacity_mbps"] == 1000.0
    assert dumped["links"]["l1"]["congested"] is True
