"""Batch link creation endpoint for fast multi-link topology building.

Rationale:
---------
When creating many links via UI (e.g., Multi-Link tool with 64 links), the current
approach of calling POST /api/links 64 times sequentially is catastrophically slow:
- Each link triggers optical recompute (~200-500ms)
- Each link triggers status recompute
- Each link bumps topology version
- Result: 64 × 500ms = 32+ seconds (waterfall hell)

This batch endpoint creates all links in a single transaction and runs recomputes
ONCE at the end, reducing 32s to ~2-3s for 64 links (10-15× speedup).

Usage:
------
POST /api/links/batch
Body: { "links": [{ "id": "...", "a_interface_id": "...", ... }, ...] }
Response: { "created": [<LinkResolvedOut>, ...], "failed": [...] }
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from backend import events
from backend.api.endpoints.links_helpers_common import normalize_status_str
from backend.api.endpoints.links_helpers_create import _dev_from_iface_id
from backend.api.schemas import LinkCreate, LinkResolvedOut
from backend.constants import ONT_CLASS, PASSIVE_INLINE
from backend.db import get_session, init_db
from backend.errors import ErrorCode, raise_error
from backend.link_rules import allowed_media_codes_for_class
from backend.models import Device, Link, LinkType, PhysicalMedium
from backend.services import recompute_coalescer as coalescer
from backend.services.event_store import append_write_path_event
from backend.services.link_policy_optical import (
    enforce_ont_placement_rules,
    enforce_pon_role_if_declared,
    enforce_single_upstream_rules,
)
from backend.services.links_service import (
    canonical_link_id,
    classify_devices_for_link,
    derive_default_length_km,
    pick_default_physical_medium_id,
)
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.status_service import evaluate_link_status
from backend.utils import ensure_default_interface

__all__ = ["router", "batch_create_links"]

router = APIRouter(tags=["links"], prefix="/links")

log = logging.getLogger("unoc.links.batch")


class BatchLinkCreateRequest(BaseModel):
    """Request body for batch link creation."""

    links: list[LinkCreate]


class BatchLinkCreateResponse(BaseModel):
    """Response body for batch link creation."""

    created: list[LinkResolvedOut]
    failed: list[dict[str, Any]]  # {"link_id": str, "error": str}


@router.post("/batch", response_model=BatchLinkCreateResponse, status_code=201)
def batch_create_links(payload: BatchLinkCreateRequest) -> BatchLinkCreateResponse:
    """Create multiple links in a single transaction with single recompute.

    Performance: ~30-50ms per link (vs 300-500ms for individual POST /api/links)
    Example: 64 links = ~2-3s total (vs 32s+ for sequential creation)

    Validations:
    - All links must pass same validation rules as individual creation
    - If any link fails validation, entire batch is rolled back
    - Optical recompute runs ONCE after all links are created

    Returns:
    - created: List of successfully created links
    - failed: List of {"link_id": str, "error": str} for any failures
    """
    init_db()
    if not payload.links:
        raise HTTPException(status_code=400, detail="No links provided")

    if len(payload.links) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Batch size limited to 1000 links (provided: {len(payload.links)})",
        )

    created_links: list[LinkResolvedOut] = []
    failed_links: list[dict[str, Any]] = []
    affected_link_ids: set[str] = set()

    log.info("Batch create request: %d links", len(payload.links))

    with get_session() as s:
        try:
            # Phase 1: Validate all links (fail fast before any DB writes)
            for link_data in payload.links:
                try:
                    _validate_link_creation(s, link_data)
                except HTTPException as e:
                    failed_links.append({"link_id": link_data.id, "error": e.detail})
                except Exception as e:
                    failed_links.append(
                        {"link_id": link_data.id, "error": f"{type(e).__name__}: {e}"}
                    )

            # If any validation failed, abort entire batch
            if failed_links:
                log.warning("Batch validation failed: %d errors", len(failed_links))
                return BatchLinkCreateResponse(created=[], failed=failed_links)

            # Phase 2: Create all links in single transaction
            for link_data in payload.links:
                try:
                    link, cls, a_dev_id, b_dev_id = _create_link_no_recompute(s, link_data)
                    affected_link_ids.add(link.id)

                    # Evaluate status (lightweight, no recompute)
                    eff = evaluate_link_status(link)
                    eff_str = normalize_status_str(eff)

                    created_links.append(
                        LinkResolvedOut(
                            id=link.id,
                            a_interface_id=link.a_interface_id,
                            b_interface_id=link.b_interface_id,
                            a_device_id=a_dev_id,
                            b_device_id=b_dev_id,
                            status=link.status,
                            effective_status=eff_str,
                            kind=link.kind,
                            admin_override_status=link.admin_override_status,
                            length_km=link.length_km,
                            physical_medium_id=link.physical_medium_id,
                            rule_id=cls.rule_id,
                        )
                    )

                except IntegrityError as ie:
                    msg = str(ie).lower()
                    if "unique" in msg or "duplicate" in msg:
                        failed_links.append(
                            {"link_id": link_data.id, "error": "Link already exists"}
                        )
                    else:
                        failed_links.append(
                            {"link_id": link_data.id, "error": f"Integrity error: {ie}"}
                        )
                except HTTPException as e:
                    failed_links.append({"link_id": link_data.id, "error": e.detail})
                except Exception as e:
                    failed_links.append(
                        {"link_id": link_data.id, "error": f"{type(e).__name__}: {e}"}
                    )

            # Commit all links at once
            if created_links:
                s.commit()
                for created in created_links:
                    append_write_path_event(
                        s,
                        "LINK_CREATED",
                        created.id,
                        {
                            "a_interface_id": created.a_interface_id,
                            "b_interface_id": created.b_interface_id,
                            "kind": str(created.kind),
                            "rule_id": created.rule_id,
                        },
                    )
                log.info("Batch committed: %d links created", len(created_links))

                # Phase 3: Single recompute for all links (MAJOR SPEEDUP)
                try:
                    tv = PATHFINDING_STORE.bump_version()

                    # Optical recompute (single pass)
                    from backend.services.optical_service import (
                        recompute_optical_paths_for_affected_onts as _recompute,
                    )

                    _recompute(link_ids=affected_link_ids)
                    log.info("Optical recompute done for %d links", len(affected_link_ids))

                    # Status recompute (coalesced)
                    for link_id in affected_link_ids:
                        coalescer.schedule(scope="links", key=link_id)

                    # Emit single batch event
                    events.publish(
                        events.Event(
                            type="links.batch.created",
                            payload={
                                "link_ids": list(affected_link_ids),
                                "count": len(created_links),
                            },
                            topo_version=tv,
                        )
                    )
                except Exception as e:
                    log.exception("Recompute failed after batch create: %s", e)

        except OperationalError as oe:
            s.rollback()
            msg = str(oe).lower()
            if "locked" in msg or "readonly" in msg:
                log.warning("SQLite busy/locked during batch create: %s", oe)
                raise HTTPException(status_code=503, detail="Database busy, retry") from oe
            raise HTTPException(status_code=500, detail=f"DB operational error: {oe}") from oe
        except Exception as e:
            s.rollback()
            log.exception("Unexpected error during batch create: %s", e)
            raise HTTPException(
                status_code=500, detail=f"Batch create error: {type(e).__name__}: {e}"
            ) from e

    return BatchLinkCreateResponse(created=created_links, failed=failed_links)


def _validate_link_creation(s, payload: LinkCreate) -> None:
    """Validate link creation without creating it (fail fast)."""
    # Check for duplicate ID
    existing = s.exec(select(Link.id).where(Link.id == payload.id)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Link already exists")

    # Check endpoints differ
    if payload.a_interface_id == payload.b_interface_id:
        raise HTTPException(status_code=400, detail="Endpoints must differ")

    # Check devices exist
    a_dev_id = _dev_from_iface_id(s, payload.a_interface_id)
    b_dev_id = _dev_from_iface_id(s, payload.b_interface_id)
    a_dev = s.get(Device, a_dev_id) if a_dev_id else None
    b_dev = s.get(Device, b_dev_id) if b_dev_id else None
    if not a_dev or not b_dev:
        raise HTTPException(status_code=400, detail="Device not found for interface")

    # Check POP restriction
    if a_dev.type.name == "POP" or b_dev.type.name == "POP":
        raise_error(ErrorCode.POP_LINK_DISALLOWED, detail_suffix="POP container endpoint")

    # Check classification
    cls = classify_devices_for_link(a_dev, b_dev)
    if not cls.allowed:
        raise_error(ErrorCode.INVALID_LINK_TYPE, detail_suffix=cls.rule_id)

    # Check ODF↔ODF cascade
    from backend.models import DeviceType

    if (a_dev.type == DeviceType.ODF) and (b_dev.type == DeviceType.ODF):
        raise_error(
            ErrorCode.LINK_INVALID_PAIRING,
            detail_suffix="Direct ODF↔ODF links (cascades) are not supported.",
        )

    # Check OLT↔ONT direct
    is_olt_ont_direct = (a_dev.type == DeviceType.OLT and b_dev.type in ONT_CLASS) or (
        b_dev.type == DeviceType.OLT and a_dev.type in ONT_CLASS
    )
    if is_olt_ont_direct:
        raise_error(
            ErrorCode.LINK_INVALID_PAIRING,
            detail_suffix="Direct OLT↔ONT links not allowed. Connect via ODF.",
        )

    # Check OLT upstream rules
    if a_dev.type == DeviceType.OLT or b_dev.type == DeviceType.OLT:
        other = b_dev if a_dev.type == DeviceType.OLT else a_dev
        if (other.type in PASSIVE_INLINE) or (other.type in ONT_CLASS):
            if other.type != DeviceType.ODF:
                raise_error(
                    ErrorCode.LINK_INVALID_UPSTREAM,
                    detail_suffix=f"ODF must connect upstream to OLT PON-port, not {other.type.name}",
                )

    # ONT placement rules
    enforce_ont_placement_rules(s, a_dev, b_dev, payload.a_interface_id, payload.b_interface_id)

    # Physical medium validation
    if payload.physical_medium_id is not None:
        if s.get(PhysicalMedium, payload.physical_medium_id) is None:
            raise HTTPException(status_code=400, detail="Invalid physical_medium_id")

    # Length validation
    if payload.length_km is not None and payload.length_km < 0:
        raise HTTPException(status_code=400, detail="length_km must be >= 0")


def _create_link_no_recompute(s, payload: LinkCreate) -> tuple[Link, Any, str, str]:
    """Create link in DB without running recompute (for batch operations).

    Returns: (link, classification, a_device_id, b_device_id)
    """
    # Get devices
    a_dev_id = _dev_from_iface_id(s, payload.a_interface_id)
    b_dev_id = _dev_from_iface_id(s, payload.b_interface_id)
    a_dev = s.get(Device, a_dev_id) if a_dev_id else None
    b_dev = s.get(Device, b_dev_id) if b_dev_id else None

    if not a_dev or not b_dev:
        raise HTTPException(status_code=400, detail="Device not found")

    # Classification
    cls = classify_devices_for_link(a_dev, b_dev)

    # Ensure interfaces
    a_if = ensure_default_interface(s, payload.a_interface_id)
    b_if = ensure_default_interface(s, payload.b_interface_id)
    if not a_if or not b_if:
        raise HTTPException(status_code=400, detail="Interface creation failed")

    # Check mgmt0
    if a_if.name == "mgmt0" or b_if.name == "mgmt0":
        raise_error(ErrorCode.INVALID_LINK_TYPE, detail_suffix="management interface")

    # Canonical ID
    a_id, b_id, canonical_id, user_order_id = canonical_link_id(
        payload.a_interface_id, payload.b_interface_id
    )
    if payload.id not in {canonical_id, user_order_id}:
        raise HTTPException(
            status_code=400, detail=f"Link id not canonical; expected '{canonical_id}'"
        )

    # PON role enforcement
    enforce_pon_role_if_declared(s, a_dev, b_dev, a_if, b_if)
    enforce_single_upstream_rules(s, a_dev, b_dev)

    # Link kind
    derived_kind = LinkType.P2P if cls.link_class == "routed_p2p" else LinkType.FIBER

    # Physical medium
    selected_pm_id: int | None = None
    if getattr(payload, "physical_medium_id", None) is None:
        selected_pm_id = pick_default_physical_medium_id(s, payload.id, a_dev, b_dev)

    pm_id_to_validate = (
        payload.physical_medium_id if payload.physical_medium_id is not None else selected_pm_id
    )
    if pm_id_to_validate is not None:
        pm_obj = s.get(PhysicalMedium, int(pm_id_to_validate))
        if pm_obj is None:
            raise HTTPException(status_code=400, detail="Invalid physical_medium_id")
        allowed = allowed_media_codes_for_class(cls.link_class)
        if allowed and pm_obj.code not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Physical medium '{pm_obj.code}' not allowed for link class '{cls.link_class}'",
            )

    # Length
    derived_length: float | None = payload.length_km
    if derived_length is None and (selected_pm_id or payload.physical_medium_id):
        pm_id = selected_pm_id or int(payload.physical_medium_id or 0)
        derived_length = derive_default_length_km(s, payload.id, pm_id)

    # Create link object
    link = Link(
        id=payload.id,
        a_interface_id=a_id,
        b_interface_id=b_id,
        kind=derived_kind,
        status=payload.status,
        admin_override_status=payload.admin_override_status,
        length_km=derived_length,
        physical_medium_id=(
            payload.physical_medium_id if payload.physical_medium_id is not None else selected_pm_id
        ),
    )
    s.add(link)

    return link, cls, a_if.device_id, b_if.device_id
