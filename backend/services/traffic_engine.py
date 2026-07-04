"""Facade for traffic engine (v2-only): keeps public API stable while code lives in backend.services.traffic.*"""

from __future__ import annotations

# Do not bind LATEST_V2_SNAPSHOT at import time; it is reassigned each tick in v2_engine.
# We'll read it from the module when needed to avoid stale references.
from backend.services.traffic import (
    LEAF_TYPES,
    TariffTrafficRunner,
    TrafficEngine,
    deterministic_rand01,
)
from backend.services.traffic import v2_engine as _v2_engine

# v2 is the only engine
ENGINE_SINGLETON = TariffTrafficRunner()


def get_v2_snapshot() -> dict | None:
    """Return latest v2 snapshot if available; otherwise None.

    We prefer the global latest snapshot so tests that call TrafficEngine().run_tick()
    without starting the background runner still expose data via the endpoint.
    """
    # Read the live module attribute to observe per-tick reassignments
    snap = getattr(_v2_engine, "LATEST_V2_SNAPSHOT", None)
    if isinstance(snap, dict):
        return snap
    # Fallback to last non-empty snapshot produced by any tick
    last_good = getattr(_v2_engine, "LAST_NONEMPTY_V2_SNAPSHOT", None)
    if isinstance(last_good, dict) and (last_good.get("devices") or last_good.get("links")):
        return last_good
    # Fallback to runner snapshot if background loop is active
    try:
        if isinstance(ENGINE_SINGLETON, TariffTrafficRunner):  # type: ignore[arg-type]
            s2 = ENGINE_SINGLETON.get_snapshot()
            if isinstance(s2, dict) and (s2.get("devices") or s2.get("links")):
                return s2
    except Exception:
        return None
    return None


__all__ = [
    "ENGINE_SINGLETON",
    "get_v2_snapshot",
    "TariffTrafficRunner",
    "TrafficEngine",
    "deterministic_rand01",
    "LEAF_TYPES",
]
