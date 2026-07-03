"""WebSocket endpoint and broadcaster wiring.

Provides a broadcaster that fans backend events to all connected
WebSocket clients under /api/ws. Uses a thread-safe bounded outbox with
coalescing and a single async dispatcher task to decouple sync emitters
from the event loop. Includes a heartbeat ping/pong to prune dead connections.
"""

import asyncio
import logging
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.events import Event as _Evt  # type: ignore
from backend.events import register_ws_publisher

if TYPE_CHECKING:  # for type mapping only
    pass  # type: ignore

router = APIRouter(tags=["realtime"], prefix="/ws")

connections: set[WebSocket] = set()

# Runtime config (tunable via env for tests)
_OUTBOX_MAXSIZE = int(os.getenv("WS_OUTBOX_MAXSIZE", "1024"))
_HEARTBEAT_INTERVAL_SEC = float(os.getenv("WS_HEARTBEAT_INTERVAL_SEC", "15"))
_HEARTBEAT_TIMEOUT_SEC = float(os.getenv("WS_HEARTBEAT_TIMEOUT_SEC", "45"))
_IDLE_SHUTDOWN_SEC = float(os.getenv("WS_IDLE_SHUTDOWN_SEC", "2"))


def _coalesce_key(msg: dict) -> str | None:
    """Return a coalescing key for a message or None if it must not coalesce."""
    etype = msg.get("type")
    payload = msg.get("payload") or {}
    if etype == "device.status.changed":
        did = payload.get("id")
        if did:
            return f"dev:{did}:status"
    if etype == "device.optical.updated":
        did = payload.get("id")
        if did:
            return f"dev:{did}:optical"
    # Per-tick metric events fully replace the previous tick's values; when the
    # outbox backs up (slow/background-throttled client) only the newest one
    # matters. Without this the 1/s full-topology payloads queue unboundedly
    # (driver of the 2026-07-03 dev-server RAM blowup).
    if etype == "deviceMetricsUpdated":
        return "metrics:device"
    if etype == "linkMetricsUpdated":
        return "metrics:link"
    # link created/deleted and others are not coalesced by default
    return None


class BoundedCoalescingQueue:
    """A bounded, thread-safe queue that coalesces by key on overflow.

    - put(msg): non-blocking; if full and a prior message with same key exists,
      it replaces that prior message; otherwise it drops the oldest item and enqueues new.
    - get(): non-blocking; returns next message or None.
    - empty(): True if no messages.
    - qsize(): approximate size.
    """

    def __init__(self, maxsize: int) -> None:
        self._maxsize = max(1, maxsize)
        self._dq: deque[dict] = deque()
        self._lock = threading.Lock()

    def qsize(self) -> int:
        with self._lock:
            return len(self._dq)

    def empty(self) -> bool:
        with self._lock:
            return not self._dq

    def _find_index_for_key(self, key: str) -> int | None:
        # search from right (newest first)
        for idx in range(len(self._dq) - 1, -1, -1):
            m = self._dq[idx]
            if _coalesce_key(m) == key:
                return idx
        return None

    def put(self, msg: dict) -> None:
        key = _coalesce_key(msg)
        with self._lock:
            # Full-replacement snapshots (metrics): always keep only the newest
            # message per key, independent of queue fullness.
            if key is not None and key.startswith("metrics:"):
                idx = self._find_index_for_key(key)
                if idx is not None:
                    self._dq[idx] = msg
                    return
            if len(self._dq) < self._maxsize:
                self._dq.append(msg)
                return
            # Full: try coalesce by replacing existing message for same key
            if key is not None:
                idx = self._find_index_for_key(key)
                if idx is not None:
                    self._dq[idx] = msg
                    return
            # Otherwise drop oldest and append
            if self._dq:
                self._dq.popleft()
            self._dq.append(msg)

    def get(self) -> dict | None:
        with self._lock:
            if not self._dq:
                return None
            return self._dq.popleft()


# Thread-safe outbox filled by Broadcaster.publish (may be called from threads)
_outbox = BoundedCoalescingQueue(_OUTBOX_MAXSIZE)
_dispatcher_task: asyncio.Task | None = None
_heartbeat_task: asyncio.Task | None = None
_last_pong: dict[WebSocket, float] = {}


def _map_event_kind(event_type: str) -> str:
    """Best-effort mapping of internal dotted event types to WS-friendly kinds.

    Keeps original type in the envelope; `kind` aligns to ARCHITECTURE §8.1 names.
    """
    return {
        "device.provisioned": "deviceCreated",
        "device.status.changed": "deviceStatusUpdated",
        "device.optical.updated": "deviceSignalUpdated",
        "device.provision.warning": "deviceProvisionWarning",
        "link.created": "linkAdded",
        "link.deleted": "linkDeleted",
        "link.override.changed": "linkOverrideUpdated",
    }.get(event_type, event_type)


async def _dispatcher_loop():
    """Single async dispatcher draining the outbox and sending to all clients."""
    global _dispatcher_task
    last_active = time.time()
    while True:
        # If there are no active connections, do not drain the outbox. Keep
        # messages queued for inspection in tests and potential future clients.
        if not connections:
            await asyncio.sleep(0.02)
            # Self-terminate when idle: no connections and outbox empty for a while
            if _outbox.empty():
                now = time.time()
                if now - last_active >= _IDLE_SHUTDOWN_SEC:
                    _dispatcher_task = None
                    return
            continue
        # Drain burst
        try:
            # Send up to N messages per tick to avoid starving other tasks
            for _ in range(256):
                if _outbox.empty():
                    break
                msg = _outbox.get()
                if msg is None:
                    break
                await broadcast_json(msg)
                last_active = time.time()
        except Exception:
            # Never crash the dispatcher
            await asyncio.sleep(0)
        # Small pause to yield loop
        await asyncio.sleep(0.02)
        # Self-terminate when idle: keep-alive handled above when no connections


async def _heartbeat_loop():
    """Periodically send ping and close stale connections without pong."""
    global _heartbeat_task
    # If no connections at start, exit quickly
    if not connections:
        _heartbeat_task = None
        return
    # Delay the first ping to avoid racing immediately after connect
    await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
    while True:
        try:
            # Send ping
            if connections:
                iso = datetime.now(UTC).isoformat()
                for c in list(connections):
                    try:
                        await c.send_json({"type": "__ping__", "ts": iso})
                    except Exception:
                        connections.discard(c)
                        _last_pong.pop(c, None)
                # Prune connections that haven't ponged within timeout
                now = time.time()
                stale: list[WebSocket] = []
                for c in list(connections):
                    last = _last_pong.get(c, 0.0)
                    if now - last > _HEARTBEAT_TIMEOUT_SEC:
                        stale.append(c)
                for c in stale:
                    connections.discard(c)
                    _last_pong.pop(c, None)
        except Exception:
            await asyncio.sleep(0)
        # If no connections remain, exit to avoid lingering background loop
        if not connections:
            _heartbeat_task = None
            return
        await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)


@router.websocket("")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Optional test aid: send a one-time hello after connect to avoid client-side races
    try:
        if os.getenv("WS_SEND_HELLO_ON_CONNECT", "0") == "1":
            await ws.send_json({"type": "__hello__", "ts": datetime.now(UTC).isoformat()})
    except Exception:
        # Never fail the connection due to a hello send error
        pass
    connections.add(ws)
    _last_pong[ws] = time.time()
    global _dispatcher_task
    if _dispatcher_task is None or _dispatcher_task.done():
        _dispatcher_task = asyncio.create_task(_dispatcher_loop())
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        while True:
            # Simple ping/pong keepalive; client may send anything. Avoid long blocking
            # reads to reduce flakiness under TestClient by using a short timeout.
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
            except TimeoutError:
                # No inbound client traffic; just loop to allow outbound dispatcher to run
                continue
            except WebSocketDisconnect:
                # Bubble up to outer handler for cleanup
                raise
            except Exception:
                # Ignore transient protocol errors and keep the connection open
                await asyncio.sleep(0)
                continue
            if msg == "ping":  # backward compatibility with earlier tests
                _last_pong[ws] = time.time()
                continue
            # Try JSON protocol for pong
            try:
                import json

                data = json.loads(msg)
                if isinstance(data, dict) and data.get("type") == "__pong__":
                    _last_pong[ws] = time.time()
            except Exception:
                # ignore non-JSON messages
                pass
    except WebSocketDisconnect:
        connections.discard(ws)
        _last_pong.pop(ws, None)
    finally:
        # Cleanup on exit; if this was the last connection, cancel background tasks
        connections.discard(ws)
        _last_pong.pop(ws, None)
    if not connections:
        try:
            if _dispatcher_task is not None and not _dispatcher_task.done():
                _dispatcher_task.cancel()
        except Exception:
            pass
        try:
            if _heartbeat_task is not None and not _heartbeat_task.done():
                _heartbeat_task.cancel()
        except Exception:
            pass
        _dispatcher_task = None
        _heartbeat_task = None


async def broadcast_json(message: dict):  # future integration with events
    dead = []
    for c in list(connections):
        try:
            await c.send_json(message)
        except Exception:
            dead.append(c)
    for c in dead:
        connections.discard(c)


class WsBroadcaster:
    """Backend events → WS message fanout.

    publish() can be invoked from sync contexts; we just enqueue and
    let the async dispatcher deliver.
    """

    def publish(self, event):  # type: ignore[no-untyped-def]
        # Build envelope
        now = datetime.now(UTC).isoformat()
        etype: str = getattr(event, "type", "unknown")
        envelope = {
            "type": etype,
            "kind": _map_event_kind(etype),
            "payload": getattr(event, "payload", {}),
            "topo_version": getattr(event, "topo_version", None),
            "correlation_id": getattr(event, "correlation_id", None),
            "ts": now,
        }
        try:
            if etype in {"deviceMetricsUpdated", "linkMetricsUpdated"}:
                logging.getLogger("unoc.ws").info(
                    "enqueue %s count=%s",
                    etype,
                    len(
                        (envelope.get("payload") or {}).get("devices")
                        or (envelope.get("payload") or {}).get("links")
                        or []
                    ),
                )
        except Exception:
            pass
        _outbox.put(envelope)


# Register direct publisher with events so BROADCASTER can enqueue without imports
def _publish_via_ws(event: _Evt) -> None:  # pragma: no cover - thin adapter
    now = datetime.now(UTC).isoformat()
    etype: str = getattr(event, "type", "unknown")
    envelope = {
        "type": etype,
        "kind": _map_event_kind(etype),
        "payload": getattr(event, "payload", {}),
        "topo_version": getattr(event, "topo_version", None),
        "correlation_id": getattr(event, "correlation_id", None),
        "ts": now,
    }
    _outbox.put(envelope)


try:  # pragma: no cover - best-effort wiring at import time
    register_ws_publisher(_publish_via_ws)
except Exception:
    pass


__all__ = [
    "broadcast_json",
    "connections",
    "router",
    "WsBroadcaster",
    "BoundedCoalescingQueue",
]
