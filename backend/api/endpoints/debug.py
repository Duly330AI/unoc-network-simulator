from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.db import get_session
from backend.models import Device
from backend.services import status_diagnostics
from backend.services.aggregation_audit import build_aggregation_audit
from backend.services.count_semantics import build_count_semantics
from backend.services.debug_snapshot import gather_full_snapshot
from backend.services.dependency_resolver import trace_l3_path_to_anchor
from backend.services.layer_validation import validate_layer_isolation
from backend.services.layered_state_model import resolve_layered_device_state
from backend.services.optical_physics_model import resolve_optical_physics_state
from backend.services.simulation_event_engine import (
    SIMULATION_EVENT_TYPES,
    build_simulation_event_log,
    replay_simulation_events,
    serialize_events,
)
from backend.services.subscriber_model import resolve_subscriber_model
from backend.services.truth_model import build_truth_model

router = APIRouter(tags=["debug"], prefix="/debug")


def _dev_enabled() -> bool:
    return os.getenv("UNOC_DEV_FEATURES", "0").strip() not in {"", "0", "false", "False"}


@router.get("/full-snapshot")
def get_full_snapshot(
    sections: str | None = Query(default=None, description="CSV list of sections to include"),
    pretty: bool = Query(default=False),
    maxItems: int | None = Query(default=None, ge=1),
    includeDeltas: bool = Query(default=True),
) -> Any:  # raw JSON dump by design
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    selected = None
    if sections:
        selected = [s.strip() for s in sections.split(",") if s.strip()]
    doc = gather_full_snapshot(
        selected_sections=selected, max_items=maxItems, include_deltas=includeDeltas
    )
    if pretty:
        # Let FastAPI handle JSON serialization; returning dict is fine. Pretty flag retained for future.
        return doc
    return doc


@router.get("/l3-path/{device_id}")
def get_l3_path(device_id: str):  # type: ignore[override]
    """Return a traced L3 path to a backbone anchor for the given device.

    Dev-only endpoint gated by UNOC_DEV_FEATURES, intended for diagnostics.
    Response: { ok: bool, reason: str|null, chain: string[] }
    """
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        d = s.get(Device, device_id)
        if not d:
            raise HTTPException(status_code=404, detail="device not found")
        res = trace_l3_path_to_anchor(s, d)
        return {
            "ok": bool(res.ok),
            "reason": res.reason,
            "chain": res.chain or [],
        }


@router.get("/status-diagnostics")
def get_status_diagnostics():  # type: ignore[override]
    """Return current in-memory status diagnostics snapshot.

    Dev-only endpoint; exposes per-device upstream_l3_ok, anchor, reason_codes,
    legacy BFS reachability flag and the evaluation timestamp. Purely
    observational in Phase 1.
    """
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    return {"devices": status_diagnostics.snapshot()}


@router.get("/subscriber-model")
def get_subscriber_model():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return resolve_subscriber_model(s)


@router.get("/device-state")
def get_device_state():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        subscriber_model = resolve_subscriber_model(s)
        optical_state = resolve_optical_physics_state(s)
        device_state = resolve_layered_device_state(s, subscriber_model, optical_state)
        device_state["validation"] = validate_layer_isolation(
            device_state, subscriber_model, optical_state
        )
        return device_state


@router.get("/optical-state")
def get_optical_state():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return resolve_optical_physics_state(s)


@router.get("/layer-leak-report")
def get_layer_leak_report():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        subscriber_model = resolve_subscriber_model(s)
        optical_state = resolve_optical_physics_state(s)
        device_state = resolve_layered_device_state(s, subscriber_model, optical_state)
        return validate_layer_isolation(device_state, subscriber_model, optical_state)


@router.get("/aggregation-audit")
def get_aggregation_audit():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return build_aggregation_audit(s)


@router.get("/count-semantics")
def get_count_semantics():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return build_count_semantics(s)


@router.get("/truth-model")
def get_truth_model():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return build_truth_model(s)


@router.get("/event-log")
def get_event_log():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        events = build_simulation_event_log(s)
        return {
            "append_only": True,
            "event_types": list(SIMULATION_EVENT_TYPES),
            "event_count": len(events),
            "events": serialize_events(events),
            "direct_mutation_guard": {
                "mode": "diagnostic_projection",
                "note": "Current SQL write paths are legacy direct mutations; this debug stream is the canonical replay source for projections.",
            },
        }


@router.get("/projections")
def get_projections():  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        return replay_simulation_events(build_simulation_event_log(s))


@router.get("/replay")
def get_replay(
    from_index: int = Query(default=0, alias="from", ge=0),
    to: int | None = Query(default=None, ge=0),
):  # type: ignore[override]
    if not _dev_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    with get_session() as s:
        events = build_simulation_event_log(s)
        end = len(events) if to is None else min(to + 1, len(events))
        replay_window = events[from_index:end]
        return {
            "from": from_index,
            "to": (end - 1) if replay_window else None,
            "events": serialize_events(replay_window),
            "projections": replay_simulation_events(replay_window),
        }
