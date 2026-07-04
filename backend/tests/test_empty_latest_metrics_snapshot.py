from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import traffic_engine
from backend.services.traffic import v2_engine


EMPTY_LATEST = {
    "lastTick": 999,
    "devices": {},
    "links": {},
}

STALE_NONEMPTY = {
    "lastTick": 100,
    "devices": {
        "old_device": {
            "bps": 1.0,
            "utilization": 0.1,
            "version": 0,
        }
    },
    "links": {
        "old_link": {
            "bps": 1.0,
            "utilization": 0.1,
            "version": 0,
        }
    },
}


def test_empty_latest_snapshot_wins_over_stale_nonempty_fallback(monkeypatch):
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", dict(EMPTY_LATEST))
    monkeypatch.setattr(v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", dict(STALE_NONEMPTY))

    snapshot = traffic_engine.get_v2_snapshot()

    assert snapshot == EMPTY_LATEST


def test_nonempty_fallback_still_works_when_latest_snapshot_absent(monkeypatch):
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", None)
    monkeypatch.setattr(v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", dict(STALE_NONEMPTY))

    snapshot = traffic_engine.get_v2_snapshot()

    assert snapshot == STALE_NONEMPTY


def test_metrics_snapshot_endpoint_returns_empty_latest_snapshot(monkeypatch):
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", dict(EMPTY_LATEST))
    monkeypatch.setattr(v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", dict(STALE_NONEMPTY))
    monkeypatch.setattr(traffic_engine.ENGINE_SINGLETON, "use_go", True, raising=False)

    response = TestClient(app).get("/api/metrics/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["lastTick"] == 999
    assert body["devices"] == {}
    assert body["links"] == {}


def test_debug_full_snapshot_metrics_v2_mirrors_empty_latest_snapshot(monkeypatch):
    monkeypatch.setenv("UNOC_DEV_FEATURES", "1")
    monkeypatch.setattr(v2_engine, "LATEST_V2_SNAPSHOT", dict(EMPTY_LATEST))
    monkeypatch.setattr(v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", dict(STALE_NONEMPTY))

    response = TestClient(app).get("/api/debug/full-snapshot", params={"sections": "metrics_v2"})

    assert response.status_code == 200
    metrics_v2 = response.json()["metrics_v2"]
    assert metrics_v2["lastTick"] == 999
    assert metrics_v2["devices"] == {}
    assert metrics_v2["links"] == {}
