import logging
import threading
import time

from .config import _cfg_bool, _cfg_float, _cfg_int

# Import Go Traffic Client
try:
    from backend.clients.traffic_go_client import TrafficGoClient

    _go_client_available = True
except ImportError:
    _go_client_available = False

# Import Prometheus metrics
try:
    from backend.api.endpoints.metrics import TRAFFIC_TICK_DURATION

    _metrics_available = True
except ImportError:
    _metrics_available = False


def _preserve_congestion_fields(target: dict, metrics: dict) -> None:
    if "congested" in metrics:
        target["congested"] = bool(metrics.get("congested"))
    if "capacity_mbps" in metrics:
        target["capacity_mbps"] = metrics.get("capacity_mbps")


# B2 shaping fields: requested (pre-shaping) demand, applied scales and the
# throttled marker. up/down_bps stay delivered traffic; never rename those.
_SHAPING_FLOAT_FIELDS = (
    "demand_up_bps",
    "demand_down_bps",
    "scale_up",
    "scale_down",
)


def _preserve_shaping_fields(target: dict, metrics: dict) -> None:
    for field in _SHAPING_FLOAT_FIELDS:
        if field in metrics:
            target[field] = metrics.get(field)
    if "throttled" in metrics:
        target["throttled"] = bool(metrics.get("throttled"))


def transform_go_snapshot_to_frontend(go_snapshot: dict) -> dict:
    """Transform Go snapshot format to frontend-expected format."""
    devices = {}
    for dev_id, metrics in go_snapshot.get("device_metrics", {}).items():
        up_mbps = metrics.get("up_mbps", 0.0)
        down_mbps = metrics.get("down_mbps", 0.0)
        total_bps = (up_mbps + down_mbps) * 1_000_000.0
        entry = {
            "bps": total_bps,
            "upstream_bps": up_mbps * 1_000_000.0,
            "downstream_bps": down_mbps * 1_000_000.0,
            "utilization": metrics.get("utilization", 0.0),
            "version": 0,
        }
        _preserve_congestion_fields(entry, metrics)
        _preserve_shaping_fields(entry, metrics)
        devices[dev_id] = entry

    links = {}
    for link_id, metrics in go_snapshot.get("link_metrics", {}).items():
        traffic_mbps = metrics.get("traffic_mbps", 0.0)
        entry = {
            "bps": traffic_mbps * 1_000_000.0,
            "utilization": metrics.get("utilization", 0.0),
            "version": 0,
        }
        _preserve_congestion_fields(entry, metrics)
        _preserve_shaping_fields(entry, metrics)
        links[link_id] = entry

    return {
        "lastTick": go_snapshot.get("tick", 0),
        "devices": devices,
        "links": links,
    }


def build_device_metric_changes(go_snapshot: dict) -> list[dict]:
    device_changes = []
    for dev_id, metrics in go_snapshot.get("device_metrics", {}).items():
        up_bps = metrics.get("up_bps", 0.0)
        down_bps = metrics.get("down_bps", 0.0)
        entry = {
            "id": dev_id,
            "bps": up_bps + down_bps,
            "upstream_bps": up_bps,
            "downstream_bps": down_bps,
            "utilization": metrics.get("utilization", 0.0),
        }
        _preserve_congestion_fields(entry, metrics)
        _preserve_shaping_fields(entry, metrics)
        device_changes.append(entry)
    return device_changes


def build_link_metric_changes(go_snapshot: dict) -> list[dict]:
    link_changes = []
    for link_id, metrics in go_snapshot.get("link_metrics", {}).items():
        up_bps = metrics.get("up_bps", 0.0)
        down_bps = metrics.get("down_bps", 0.0)
        entry = {
            "id": link_id,
            "bps": up_bps + down_bps,
            "utilization": metrics.get("utilization", 0.0),
        }
        _preserve_congestion_fields(entry, metrics)
        _preserve_shaping_fields(entry, metrics)
        link_changes.append(entry)
    return link_changes


class TariffTrafficRunner:
    def __init__(self) -> None:
        # Enabled by default; can be disabled via env TRAFFIC_ENABLED=false
        self.enabled = _cfg_bool("TRAFFIC_ENABLED", True)
        self.interval = _cfg_float("TRAFFIC_TICK_INTERVAL_SEC", 1.0)
        self.seed = _cfg_int("TRAFFIC_RANDOM_SEED", 12345)

        # ⚡ FORCE Go Traffic Engine - Python fallback removed for performance
        self.use_go = True
        if not _go_client_available:
            raise RuntimeError(
                "❌ Go Traffic Client not available! Install traffic_go_client package."
            )

        try:
            self._go_client = TrafficGoClient(base_url="http://localhost:8080", timeout=10.0)
            health = self._go_client.health()
            self._log_init = logging.getLogger("traffic.TariffTrafficRunner")
            self._log_init.info(
                "✅ Go Traffic Engine CONNECTED (FORCED): %s", health.get("version", "unknown")
            )
            self.engine = None  # No Python engine
        except Exception as e:
            raise RuntimeError(f"❌ Go Traffic Engine connection FAILED: {e}") from e

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._log = logging.getLogger("traffic.TariffTrafficRunner")

    def start(self) -> None:
        if not self.enabled:
            self._log.info("TrafficEngineV2 disabled (TRAFFIC_ENABLED=false). Runner not started.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        engine_type = "Go" if self.use_go else "Python"
        self._thread = threading.Thread(
            target=self._run_loop, name=f"TrafficEngine{engine_type}", daemon=True
        )
        self._log.info(
            "Starting TrafficEngine%s: interval=%.3fs seed=%s",
            engine_type,
            self.interval,
            str(self.seed),
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=timeout)
        self._log.info("TrafficEngineV2 stopped")
        self._thread = None

    def _transform_go_to_frontend(self, go_snapshot: dict) -> dict:
        """Transform Go snapshot format to frontend-expected format.

        Go format:
        {
            "tick": 289,
            "device_metrics": {"dev_id": {"up_mbps": float, "down_mbps": float}},
            "link_metrics": {"link_id": {"traffic_mbps": float, "utilization": float}}
        }

        Frontend format:
        {
            "lastTick": 289,
            "devices": {"dev_id": {"bps": float, "upstream_bps": float, "downstream_bps": float, "utilization": float}},
            "links": {"link_id": {"bps": float, "utilization": float}}
        }
        """
        return transform_go_snapshot_to_frontend(go_snapshot)

    def _run_loop(self) -> None:
        # Import here to avoid circular dependency
        from backend.events import Event, publish

        from . import v2_engine as _v2_engine

        while not self._stop.is_set():
            t0 = time.time()
            try:
                if self.use_go and self._go_client:
                    result = self._go_client.tick()
                    # Instrument Prometheus metrics with Go results
                    if _metrics_available and result:
                        duration_sec = result.get("duration_ms", 0) / 1000.0
                        TRAFFIC_TICK_DURATION.observe(duration_sec)

                    # Fetch Go snapshot and transform to frontend format
                    go_snapshot = self._go_client.snapshot()
                    if go_snapshot:
                        # Transform Go format to frontend format
                        frontend_snapshot = self._transform_go_to_frontend(go_snapshot)
                        _v2_engine.LATEST_V2_SNAPSHOT = frontend_snapshot
                        if frontend_snapshot.get("devices") or frontend_snapshot.get("links"):
                            _v2_engine.LAST_NONEMPTY_V2_SNAPSHOT = frontend_snapshot

                        # Publish WebSocket events for frontend updates
                        tick = go_snapshot.get("tick", 0)

                        # Device metrics updates
                        device_changes = build_device_metric_changes(go_snapshot)

                        publish(
                            Event(
                                type="deviceMetricsUpdated",
                                payload={
                                    "devices": device_changes,
                                    "tick": tick,
                                    "authoritative": True,
                                },
                            )
                        )

                        # Link metrics updates
                        link_changes = build_link_metric_changes(go_snapshot)

                        publish(
                            Event(
                                type="linkMetricsUpdated",
                                payload={
                                    "links": link_changes,
                                    "tick": tick,
                                    "authoritative": True,
                                },
                            )
                        )

                elif self.engine:
                    self.engine.run_tick()
            except Exception:
                # Never kill the tick loop, but a silently swallowed error made
                # dead ticks invisible; log at most one full traceback per minute.
                now = time.time()
                if now - getattr(self, "_last_tick_error_log", 0.0) >= 60.0:
                    self._last_tick_error_log = now
                    self._log.exception("traffic tick failed")
            t1 = time.time()
            rem = max(0.0, self.interval - (t1 - t0))
            if self._stop.wait(rem):
                break

    def get_snapshot(self) -> dict:
        if self.use_go and self._go_client:
            return self._go_client.snapshot()
        elif self.engine:
            return self.engine.get_snapshot()
        return {"device_metrics": {}, "link_metrics": {}}
