"""Delete helper for devices.

Separated to keep modules small and under file-length budget. Public API is
re-exported from devices_helpers_mutation.py.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from backend.models import (
    BridgeDomain,
    Device,
    Interface,
    InterfaceAddress,
    MacAddressEntry,
    Neighbor,
    ProvisioningRecord,
    Route,
)
from backend.services.pathfinding import PATHFINDING_STORE
from backend.services.event_store import append_write_path_event

logger = logging.getLogger(__name__)


def delete_device_impl(s: Session, device_id: str) -> None:
    d = s.get(Device, device_id)
    if not d:
        raise LookupError("Not found")
    device_type = str(getattr(d.type, "value", d.type))

    logger.info("delete_device_impl: deleting %s", device_id)

    # Get all interfaces first (needed for cascade deletion)
    interfaces = s.exec(select(Interface).where(Interface.device_id == device_id)).all()
    iface_ids = [i.id for i in interfaces]
    deleted_link_ids: set[str] = set()
    logger.info("delete_device_impl: found %d interfaces", len(iface_ids))

    # Delete interface-related entities FIRST (before BridgeDomain!)
    if iface_ids:
        from backend.models import Link  # local import to avoid circulars at module import time

        for pr in s.exec(
            select(ProvisioningRecord).where(ProvisioningRecord.device_id == device_id)
        ):
            s.delete(pr)
        logger.info("delete_device_impl: deleted device-level provisioning records")

        for ifid in iface_ids:
            logger.info("delete_device_impl: cleaning interface %s", ifid)
            for link in s.exec(select(Link).where(Link.a_interface_id == ifid)):
                deleted_link_ids.add(link.id)
                s.delete(link)
            for link in s.exec(select(Link).where(Link.b_interface_id == ifid)):
                deleted_link_ids.add(link.id)
                s.delete(link)
            for ia in s.exec(select(InterfaceAddress).where(InterfaceAddress.interface_id == ifid)):
                s.delete(ia)
            for me in s.exec(select(MacAddressEntry).where(MacAddressEntry.interface_id == ifid)):
                s.delete(me)
            for nb in s.exec(select(Neighbor).where(Neighbor.interface_id == ifid)):
                s.delete(nb)
            for rt in s.exec(select(Route).where(Route.interface_id == ifid)):
                s.delete(rt)
            for pr in s.exec(
                select(ProvisioningRecord).where(ProvisioningRecord.interface_id == ifid)
            ):
                s.delete(pr)
            iface = s.get(Interface, ifid)
            if iface is not None:
                s.delete(iface)
            logger.info("delete_device_impl: interface %s and dependencies removed", ifid)
        s.flush()

    # Delete BridgeDomains AFTER interfaces (to avoid FK violation from interface.bridge_domain_id)
    bridge_domains = s.exec(select(BridgeDomain).where(BridgeDomain.device_id == device_id)).all()
    logger.info("delete_device_impl: found %d bridge domains", len(bridge_domains))
    for bd in bridge_domains:
        s.delete(bd)
        logger.info("delete_device_impl: bridge domain %s deleted", bd.id)
    if bridge_domains:
        s.flush()

    # Finally delete the device itself
    s.delete(d)
    s.commit()
    logger.info("delete_device_impl: device %s deleted", device_id)
    PATHFINDING_STORE.bump_version()
    append_write_path_event(
        s,
        "DEVICE_DELETED",
        device_id,
        {"device_type": device_type, "interface_count": len(iface_ids)},
    )
    for link_id in sorted(deleted_link_ids):
        append_write_path_event(s, "LINK_DELETED", link_id, {"deleted_by_device_id": device_id})

    # NOTE: PON occupancy cache automatically invalidates via provisioning_count in cache key
    # No manual invalidation needed - cache reacts to ONT provision state changes

    return None
