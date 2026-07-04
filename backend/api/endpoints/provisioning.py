from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend import events
from backend.api.schemas import DeviceOut, ProvisionResponse
from backend.clients.go_services.status_client import get_status_client
from backend.db import get_session, init_db
from backend.models import Device
from backend.services import recompute_coalescer as coalescer
from backend.services.background import _recompute_after_device_provision, schedule
from backend.services.event_store_runtime import projection_write_context
from backend.services.provisioning_service import provision_device
from backend.services.status_service import evaluate_device_status

router = APIRouter(tags=["provisioning"], prefix="/devices")


@router.post("/{device_id}/provision", response_model=ProvisionResponse)
def provision_device_endpoint(device_id: str, background: BackgroundTasks):
    # Covered write surface: run inside projection context for the bypass guard
    with projection_write_context():
        return _provision_device_guarded(device_id, background)


def _provision_device_guarded(device_id: str, background: BackgroundTasks):
    init_db()
    with get_session() as s:
        d = s.get(Device, device_id)
        if not d:
            raise HTTPException(status_code=404, detail="Not found")
        # Capture before for event emission
        before = evaluate_device_status(d)
        d = provision_device(s, d)
        s.commit()
        # device.provisioned is emitted by service layer for both API and direct calls
        # Schedule consolidated status recompute instead of direct call
        try:
            coalescer.schedule(scope="devices", key=d.id)
        except Exception:  # pragma: no cover
            pass
        try:
            status_client = get_status_client()
            if status_client:
                status_client.propagate_status(
                    changed_device_ids=[d.id], changed_link_ids=[], update_database=True
                )
        except Exception as e:
            # Best-effort; the coalescer schedule remains as a fallback.
            print(f"[WARN] Status propagation failed after provision: {e}")
        # Offload optical recompute to background
        schedule(background, _recompute_after_device_provision, d.id)
        # Emit device.status.changed immediately if transitioned
        try:
            after = evaluate_device_status(d)
            if before != after:
                # Use current topology version for deterministic ordering
                from backend.services.pathfinding import PATHFINDING_STORE as _pf

                tv_now = _pf.bump_version()
                events.publish(
                    events.Event(
                        type="device.status.changed",
                        payload={
                            "id": d.id,
                            "status": str(after),
                            "effective_status": str(after),
                            "admin_override_status": (
                                str(getattr(d, "admin_override_status", None))
                                if getattr(d, "admin_override_status", None)
                                else None
                            ),
                        },
                        topo_version=tv_now,
                    )
                )
        except Exception:
            pass
        # Recompute remains asynchronous and coalesced; no inline flush here.
        s.refresh(d)
        return ProvisionResponse(device=DeviceOut.from_model(d))
