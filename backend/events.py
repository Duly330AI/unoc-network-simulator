"""Event shape stubs (placeholder).

Defines minimal type aliases and a no-op broadcaster to decouple future
WebSocket/event bus work from current business logic.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

EventType = Literal[
    "device.provisioned",
    "device.status.changed",
    "link.created",
    "link.deleted",
    "link.override.changed",
    "link.status.changed",
    "device.provision.warning",
    "device.optical.updated",
    "linkMetricsUpdated",
    "deviceMetricsUpdated",
    "device.congestion.detected",
    "device.congestion.cleared",
    "link.congestion.detected",
    "link.congestion.cleared",
    "segment.congestion.detected",
    "segment.congestion.cleared",
]


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any]
    topo_version: int | None = None
    correlation_id: str | None = None


class Broadcaster(Protocol):
    def publish(self, event: Event) -> None:  # pragma: no cover - interface
        ...


class NoOpBroadcaster:
    def publish(self, event: Event) -> None:  # pragma: no cover
        # Intentionally no-op; replace with real implementation later.
        return None


_EVENT_COUNTER: Counter[str] = Counter()
# Lightweight in-memory history for tests / introspection (TASK-053 test support)
_EVENT_HISTORY: list[Event] = []
# Hold the current concrete broadcaster; mutated by set_broadcaster.
_CURRENT_BROADCASTER: Broadcaster = NoOpBroadcaster()

# Optional websocket publish hook (registered by ws module at import time)
_WS_PUBLISH: Callable[[Event], None] | None = None

_NON_PERSISTED_RUNTIME_EVENT_TYPES = frozenset(
    {
        "deviceMetricsUpdated",
        "linkMetricsUpdated",
        "device.congestion.detected",
        "device.congestion.cleared",
        "link.congestion.detected",
        "link.congestion.cleared",
        "segment.congestion.detected",
        "segment.congestion.cleared",
    }
)


class DelegatingBroadcaster:
    """Proxy that always forwards to the current broadcaster.

    This avoids import-order pitfalls in tests like `from backend.events import BROADCASTER`
    by ensuring the object they import will still route to the broadcaster set later
    via `set_broadcaster(...)`.
    """

    def publish(self, event: Event) -> None:  # pragma: no cover - trivial delegation
        """Synchronous, deterministic fanout with import-order tolerance.

        Contract:
        - Enqueue a mapped envelope into the websocket outbox (best-effort), so tests
          reading the outbox see messages even without explicit wiring.
        - Also delegate to the currently installed broadcaster so CaptureBroadcaster
          (and others) still receive events. To avoid duplicate outbox enqueues, skip
          delegating if the current broadcaster is WsBroadcaster and we already
          enqueued directly.
        - Never raise; swallow errors to keep emitters non-blocking.
        """
        ws_enqueued = False

        # 1) Best-effort: direct enqueue to WS outbox with mapped envelope
        try:
            import sys as _sys
            from datetime import UTC, datetime

            _ws_mod = _sys.modules.get("backend.api.endpoints.ws")
            if _ws_mod is None:  # lazily import if not already loaded
                from backend.api.endpoints import ws as _ws_mod  # type: ignore

            now = datetime.now(UTC).isoformat()
            etype: str = getattr(event, "type", "unknown")
            envelope = {
                "type": etype,
                "kind": getattr(_ws_mod, "_map_event_kind", lambda x: x)(etype),
                "payload": getattr(event, "payload", {}),
                "topo_version": getattr(event, "topo_version", None),
                "correlation_id": getattr(event, "correlation_id", None),
                "ts": now,
            }
            _ws_mod._outbox.put(envelope)
            ws_enqueued = True
        except Exception:
            # ignore any issues with ws module/outbox
            pass

        # 2) If direct enqueue failed, try a registered WS publisher hook
        if not ws_enqueued:
            try:
                if _WS_PUBLISH is not None:
                    _WS_PUBLISH(event)
                    ws_enqueued = True
            except Exception:
                pass

        # 3) Delegate to the currently installed broadcaster unless it would
        #    duplicate the WS outbox enqueue.
        try:
            b = _CURRENT_BROADCASTER
            is_ws_broadcaster = False
            try:
                from backend.api.endpoints.ws import WsBroadcaster as _WsB  # type: ignore

                is_ws_broadcaster = isinstance(b, _WsB)  # type: ignore[arg-type]
            except Exception:
                is_ws_broadcaster = False

            if not (is_ws_broadcaster and ws_enqueued):
                b.publish(event)
        except Exception:
            # swallow broadcaster errors
            pass


# Export a stable proxy object that delegates to the current broadcaster.
BROADCASTER: Broadcaster = DelegatingBroadcaster()


def set_broadcaster(b: Broadcaster) -> None:
    """Swap the global broadcaster (testing / runtime injection)."""
    global _CURRENT_BROADCASTER
    _CURRENT_BROADCASTER = b


def register_ws_publisher(publish_fn: Callable[[Event], None]) -> None:
    """Register a direct publisher from the websocket module.

    This lets BROADCASTER.publish(event) enqueue messages even if the app wiring
    hasn't swapped the broadcaster yet.
    """
    global _WS_PUBLISH
    _WS_PUBLISH = publish_fn


def record_event(event: Event) -> None:
    _EVENT_COUNTER[event.type] += 1
    _EVENT_HISTORY.append(event)


def publish(event: Event) -> None:
    """Publish an event via the configured broadcaster and record it.

    This is the preferred entry point for emitting events so that internal
    counters/history stay consistent while the realtime layer is notified.
    """
    try:
        # Use the proxy to route to current broadcaster regardless of import order.
        BROADCASTER.publish(event)
    finally:
        # Always record even if broadcaster fails
        record_event(event)
        if event.type not in _NON_PERSISTED_RUNTIME_EVENT_TYPES:
            try:
                from backend.services.event_store import append_runtime_event

                append_runtime_event(event)
            except Exception:
                pass


def get_event_counts() -> dict[str, int]:
    return dict(_EVENT_COUNTER)


def get_event_history() -> list[Event]:
    # Return a shallow copy to avoid accidental external mutation
    return list(_EVENT_HISTORY)


def reset_events() -> None:
    _EVENT_COUNTER.clear()
    _EVENT_HISTORY.clear()


__all__ = [
    "Event",
    "EventType",
    "BROADCASTER",
    "NoOpBroadcaster",
    "set_broadcaster",
    "register_ws_publisher",
    "publish",
    "record_event",
    "get_event_counts",
    "get_event_history",
    "reset_events",
]

# Intentionally avoid importing the websocket module here to prevent circular-import
# timing issues during tests. The websocket module registers a direct publisher via
# `register_ws_publisher`, and application startup may call `set_broadcaster`.
