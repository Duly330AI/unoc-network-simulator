"""Optical recompute & signal budget service (TASK-035).

Computes the optical signal budget for affected ONTs using the
optical path resolver and persists results on the Device model:
    - signal_power_dbm (received power at ONT)
    - signal_margin_db (relative to ONT sensitivity)
    - signal_status (OK/WARNING/CRITICAL/NO_SIGNAL)

Emits `device.optical.updated` events for each ONT whose values changed
or when explicitly triggered by topology changes.
"""

from __future__ import annotations

import logging

from sqlmodel import select

from backend import events
from backend.clients.go_services.optical_client import get_optical_client
from backend.db import get_session, init_db
from backend.models import Device, DeviceType, Status
from backend.services.catalog_effective import (
    get_effective_sensitivity_dbm,
    get_effective_tx_power_dbm,
)
from backend.services.event_store_runtime import projection_write
from backend.services.status_recompute import recompute_devices_status
from backend.services.status_service import evaluate_device_status

log = logging.getLogger("unoc.optical")

# Passive optical-relevant device types (future expansion)
OPTICAL_RELEVANT_DEVICE_TYPES = {
    "OLT",
    "ONT",
    "BUSINESS_ONT",
    "ODF",
    "NVT",
    "SPLITTER",
    "HOP",
}


# Internal derived-state writer (signal fields), not a domain mutation surface;
# explicitly excluded from the EventStore bypass guard.
@projection_write
def recompute_optical_paths_for_affected_onts(
    device_ids: set[str] | None = None, link_ids: set[str] | None = None
) -> None:
    """Recompute signal budgets for ONTs impacted by given devices/links.

    Minimal impact resolution: when in doubt, recompute all ONTs.
    """
    init_db()
    device_ids = device_ids or set()
    link_ids = link_ids or set()
    log.info(
        "Optical recomputation triggered for devices=%s links=%s",
        sorted(device_ids),
        sorted(link_ids),
    )

    # Determine candidate ONTs to recompute. For simplicity and correctness
    # in MVP, recompute all provisioned ONTs and Business ONTs. Later we can
    # optimize using the path cache dependency map.
    with get_session() as s:
        onts = s.exec(
            select(Device).where(
                (Device.type == DeviceType.ONT) | (Device.type == DeviceType.BUSINESS_ONT)
            )
        ).all()

        updated: list[Device] = []
        baseline_status: dict[str, Status] = {}

        # Get GO client (defaults to use_fallback=True for Python fallback)
        optical_client = get_optical_client()

        for ont in onts:
            # Capture dynamic status before modifications for transition detection
            try:
                before_dyn = evaluate_device_status(ont)
            except Exception:
                before_dyn = None  # type: ignore[assignment]
            prev_power = getattr(ont, "signal_power_dbm", None)
            prev_margin = getattr(ont, "signal_margin_db", None)
            prev_status = getattr(ont, "signal_status", None)
            prev_attenuation = getattr(
                ont, "attenuation_db", None
            )  # ✅ NEW: Track attenuation changes

            # Resolve path via GO service (with Python fallback)
            result = optical_client.get_path(ont_id=ont.id)
            if not result or not result.get("path_exists"):
                # No path or not found → NO_SIGNAL
                try:
                    log.info(
                        "optical: ont=%s path=None -> signal_status=NO_SIGNAL (power=None, margin=None)",
                        ont.id,
                    )
                except Exception:
                    pass
                ont.signal_power_dbm = None
                ont.signal_margin_db = None
                ont.signal_status = Device.SignalStatus.NO_SIGNAL
            else:
                # Load OLT and compute received power
                olt = s.get(Device, result["olt_id"])
                tx = get_effective_tx_power_dbm(s, olt) if olt else 0.0
                # Safe access: Go service might not always return attenuation
                total_loss = float(result.get("total_attenuation_db", 0.0))

                # DEBUG: Log what we got from PathFinder
                log.info(
                    "DEBUG PathFinder response for %s: total_attenuation_db=%s (raw: %s)",
                    ont.id,
                    total_loss,
                    result.get("total_attenuation_db", "MISSING!"),
                )

                received = tx - total_loss
                # Margin relative to ONT sensitivity
                sensitivity = get_effective_sensitivity_dbm(s, ont)
                margin = received - sensitivity

                # Classify
                if margin < 0:
                    status = Device.SignalStatus.NO_SIGNAL
                elif margin < 3.0:
                    status = Device.SignalStatus.CRITICAL
                elif margin < 6.0:
                    status = Device.SignalStatus.WARNING
                else:
                    status = Device.SignalStatus.OK

                ont.signal_power_dbm = float(received)
                ont.signal_margin_db = float(margin)
                ont.signal_status = status
                ont.attenuation_db = total_loss  # ✅ NEW: Persist attenuation!
                try:
                    log.info(
                        "optical: ont=%s olt=%s loss_db=%.3f tx=%.2f recv_dbm=%.2f sens=%.2f margin=%.2f -> %s",
                        ont.id,
                        (olt.id if olt else None),
                        total_loss,
                        tx,
                        received,
                        sensitivity,
                        margin,
                        str(status),
                    )
                except Exception:
                    pass

            # Persist and emit event if changed meaningfully
            changed = (
                prev_status != ont.signal_status
                or (prev_power is None) != (ont.signal_power_dbm is None)
                or (prev_margin is None) != (ont.signal_margin_db is None)
                or (prev_attenuation is None)
                != (ont.attenuation_db is None)  # ✅ NEW: Check attenuation changes
                or (
                    prev_power is not None
                    and ont.signal_power_dbm is not None
                    and abs(prev_power - ont.signal_power_dbm) >= 0.1
                )
                or (
                    prev_attenuation is not None
                    and ont.attenuation_db is not None
                    and abs(prev_attenuation - ont.attenuation_db)
                    >= 0.01  # ✅ NEW: Trigger on 0.01 dB change
                )
            )

            if changed:
                if before_dyn is not None:
                    baseline_status[ont.id] = before_dyn  # type: ignore[index]
                updated.append(ont)

        # Commit all changes in batch
        if updated:
            for d in updated:
                s.add(d)
            s.commit()
            try:
                from backend.api.endpoints.devices_helpers_query import bump_devices_cache_epoch

                bump_devices_cache_epoch("optical_recompute")
            except Exception:  # pragma: no cover
                log.exception("Failed to invalidate devices cache after optical recompute")
            for d in updated:
                signal_status = (
                    getattr(d.signal_status, "value", str(d.signal_status))
                    if d.signal_status
                    else None
                )
                evt = events.Event(
                    type="device.optical.updated",
                    payload={
                        "id": d.id,
                        "signal_power_dbm": d.signal_power_dbm,
                        "signal_margin_db": d.signal_margin_db,
                        "signal_status": signal_status,
                        "received_dbm": d.signal_power_dbm,
                        "margin_db": d.signal_margin_db,
                        "attenuation_db": d.attenuation_db,
                        "total_path_attenuation_db": d.attenuation_db,
                    },
                )
                events.publish(evt)
            # After emitting optical updates, recompute device status transitions for affected ONTs
            try:
                _ = recompute_devices_status(
                    s,
                    [d.id for d in updated],
                    baseline_status=baseline_status,
                )
            except Exception:  # pragma: no cover
                log.exception(
                    "Status recompute after optical updates failed for %s",
                    [d.id for d in updated],
                )
