"""Provisioning service tests.

Validates:
 - Successful single provision with IP allocation
 - Double provisioning rejection (ALREADY_PROVISIONED)
 - Pool exhaustion (simulated small CIDR override)

References ARCHITECTURE.md §§3.3 (Algorithm), 3.5 (Error Codes), 4.1 (IPAM pools).
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from backend.db import engine, init_db, reset_db
from backend.main import app
from backend.models import (
    VRF,
    Device,
    DeviceType,
    Interface,
    InterfaceAddress,
    Link,
    LinkType,
    Prefix,
)
from backend.services.provisioning_service import provision_device


def _seed_base_ipam(session: Session) -> int:
    """Create VRF 'mgmt' and required default prefixes for tests. Return vrf_id."""
    vrf = session.exec(select(VRF).where(VRF.name == "mgmt")).first()
    if not vrf:
        vrf = VRF(name="mgmt")
        session.add(vrf)
        session.commit()
        session.refresh(vrf)
    assert vrf.id is not None
    # Ensure OLT and AON mgmt prefixes exist (core_mgmt is added per-test where needed)
    existing = session.exec(select(Prefix).where(Prefix.description == "olt_mgmt")).first()
    if not existing:
        session.add(Prefix(prefix="10.250.4.0/24", vrf_id=vrf.id, description="olt_mgmt"))
    existing = session.exec(select(Prefix).where(Prefix.description == "aon_mgmt")).first()
    if not existing:
        session.add(Prefix(prefix="10.250.2.0/24", vrf_id=vrf.id, description="aon_mgmt"))
    session.commit()
    return vrf.id


def setup_function(_: object):
    reset_db()
    init_db()
    with Session(engine) as s:
        _seed_base_ipam(s)


def _dev(id_: str, t: DeviceType) -> Device:
    return Device(id=id_, name=id_, type=t)


def _add_iface(session: Session, device: Device, name: str) -> str:
    iface_id = f"{device.id}-{name}"
    if session.get(Interface, iface_id) is None:
        session.add(Interface(id=iface_id, device_id=device.id, name=name))
    return iface_id


def _connect(
    session: Session,
    a: Device,
    b: Device,
    a_port: str = "if0",
    b_port: str = "if0",
    kind: LinkType = LinkType.FIBER,
) -> str:
    a_if = _add_iface(session, a, a_port)
    b_if = _add_iface(session, b, b_port)
    link_id = "__".join(sorted([a_if, b_if]))
    if session.get(Link, link_id) is None:
        session.add(
            Link(
                id=link_id,
                a_interface_id=a_if,
                b_interface_id=b_if,
                kind=kind,
            )
        )
    return link_id


def _connect_olt_to_ont(session: Session, olt: Device, ont: Device, odf_id: str) -> Device:
    odf = _dev(odf_id, DeviceType.ODF)
    session.add(odf)
    session.flush()
    _connect(session, olt, odf, "pon0", "in0")
    _connect(session, odf, ont, "out0", "pon0")
    return odf


def test_single_provision_core_router_allocates_ip():
    with Session(engine) as s:
        # Create management prefix for core devices
        vrf_id = _seed_base_ipam(s)
        core_pref = Prefix(prefix="10.250.100.0/24", vrf_id=vrf_id, description="core_mgmt")
        s.add(core_pref)
        s.commit()
        s.refresh(core_pref)
        d = _dev("core1", DeviceType.CORE_ROUTER)
        s.add(d)
        s.commit()
        s.refresh(d)
        provision_device(s, d)
        s.commit()
        s.refresh(d)
        assert d.provisioned is True
        # mgmt interface address exists and is within the core_mgmt prefix
        addr = s.exec(
            select(InterfaceAddress).where(InterfaceAddress.interface_id == "core1-mgmt0")
        ).first()
        assert addr is not None
        assert addr.prefix_id == core_pref.id


def test_double_provision_rejected():
    with Session(engine) as s:
        # Ensure core_mgmt prefix exists
        vrf_id = _seed_base_ipam(s)
        s.add(Prefix(prefix="10.250.101.0/24", vrf_id=vrf_id, description="core_mgmt"))
        s.commit()
        d = _dev("core2", DeviceType.CORE_ROUTER)
        s.add(d)
        s.commit()
        provision_device(s, d)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, d)
        assert e.value.status_code == 409
        assert e.value.detail == "ALREADY_PROVISIONED"


def test_pool_exhaustion():
    # Simulate tiny prefix by inserting a small /30 network (2 hosts)
    with Session(engine) as s:
        vrf_id = _seed_base_ipam(s)
        tiny_prefix = Prefix(prefix="10.9.9.0/30", vrf_id=vrf_id, description="core_mgmt")
        s.add(tiny_prefix)
        # two devices -> two IPs, third should exhaust
        devs = [_dev(f"core{i}", DeviceType.CORE_ROUTER) for i in range(1, 4)]
        for d in devs:
            s.add(d)
        s.commit()
        # first two succeed
        provision_device(s, devs[0])
        provision_device(s, devs[1])
        s.commit()
        # third should raise POOL_EXHAUSTED
        with pytest.raises(HTTPException) as e:
            provision_device(s, devs[2])
        assert e.value.status_code == 409
        assert e.value.detail == "POOL_EXHAUSTED"


def test_parent_optional_missing_pop_allows_provision_for_olt():
    """OLT without POP parent is allowed; only upstream dependency must be satisfied."""
    with Session(engine) as s:
        # Seed core_mgmt (for mgmt ip), and minimal path core <-> olt
        vrf_id = _seed_base_ipam(s)
        s.add(Prefix(prefix="10.250.101.0/24", vrf_id=vrf_id, description="core_mgmt"))
        core = _dev("core_up", DeviceType.CORE_ROUTER)
        olt = _dev("olt_no_parent", DeviceType.OLT)
        s.add(core)
        s.add(olt)
        s.commit()
        s.add(Interface(id=f"{core.id}-if0", device_id=core.id, name="if0"))
        s.add(Interface(id=f"{olt.id}-if0", device_id=olt.id, name="if0"))
        s.add(
            Link(
                id=f"{core.id}-{olt.id}",
                a_interface_id=f"{core.id}-if0",
                b_interface_id=f"{olt.id}-if0",
                kind=LinkType.FIBER,
            )
        )
        s.commit()
        provision_device(s, olt)
        s.commit()
        s.refresh(olt)
        assert olt.provisioned is True


def test_parent_required_wrong_parent_type():
    """OLT with non-POP parent should fail."""
    with Session(engine) as s:
        wrong_parent = _dev("core_parent", DeviceType.CORE_ROUTER)
        olt = Device(
            id="olt_wrong_parent",
            name="olt_wrong_parent",
            type=DeviceType.OLT,
            parent_container_id="core_parent",
        )
        s.add(wrong_parent)
        s.add(olt)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, olt)
        assert e.value.status_code == 422
        assert "expected parent DeviceType.POP" in e.value.detail


def test_parent_required_positive_case():
    """OLT with valid POP parent provisions successfully."""
    with Session(engine) as s:
        pop = _dev("pop1", DeviceType.POP)
        core = _dev("core_pre", DeviceType.CORE_ROUTER)
        olt = Device(
            id="olt_ok",
            name="olt_ok",
            type=DeviceType.OLT,
            parent_container_id="pop1",
        )
        s.add(pop)
        s.add(core)
        s.add(olt)
        s.commit()
        # Add minimal interfaces and a logical adjacency core<->olt to satisfy strict path
        s.add(Interface(id=f"{core.id}-if0", device_id=core.id, name="if0"))
        s.add(Interface(id=f"{olt.id}-if0", device_id=olt.id, name="if0"))
        s.add(
            Link(
                id=f"{core.id}-{olt.id}",
                a_interface_id=f"{core.id}-if0",
                b_interface_id=f"{olt.id}-if0",
                kind=LinkType.FIBER,
            )
        )
        s.commit()
        provision_device(s, olt)
        s.commit()
        s.refresh(olt)
        assert olt.provisioned is True


def test_ont_without_upstream_path_cannot_be_provisioned():
    with Session(engine) as s:
        ont = _dev("ont_no_path", DeviceType.ONT)
        s.add(ont)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, ont)
        assert e.value.status_code == 400
        assert e.value.detail == "Cannot provision ONT: no valid provisioned OLT path found."
        s.refresh(ont)
        assert ont.provisioned is False


def test_ont_path_to_unprovisioned_olt_cannot_be_provisioned():
    with Session(engine) as s:
        olt = _dev("olt_unprovisioned_parent", DeviceType.OLT)
        ont = _dev("ont_waiting_for_olt", DeviceType.ONT)
        s.add(olt)
        s.add(ont)
        s.flush()
        _connect_olt_to_ont(s, olt, ont, "odf_unprovisioned_parent")
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, ont)
        assert e.value.status_code == 400
        assert e.value.detail == "Cannot provision ONT: no valid provisioned OLT path found."
        s.refresh(ont)
        assert ont.provisioned is False


def test_ont_with_valid_provisioned_olt_path_can_be_provisioned():
    with Session(engine) as s:
        core = _dev("core_for_ont_parent", DeviceType.CORE_ROUTER)
        olt = _dev("olt_provisioned_parent", DeviceType.OLT)
        ont = _dev("ont_with_parent_path", DeviceType.ONT)
        s.add(core)
        s.add(olt)
        s.add(ont)
        s.flush()
        _connect(s, core, olt, "if0", "uplink0")
        _connect_olt_to_ont(s, olt, ont, "odf_for_ont_parent")
        s.commit()
        provision_device(s, olt)
        provision_device(s, ont)
        s.refresh(ont)
        assert ont.provisioned is True


def test_business_ont_with_valid_provisioned_olt_path_can_be_provisioned():
    with Session(engine) as s:
        core = _dev("core_for_business_ont_parent", DeviceType.CORE_ROUTER)
        olt = _dev("olt_business_parent", DeviceType.OLT)
        ont = _dev("business_ont_with_parent_path", DeviceType.BUSINESS_ONT)
        s.add(core)
        s.add(olt)
        s.add(ont)
        s.flush()
        _connect(s, core, olt, "if0", "uplink0")
        _connect_olt_to_ont(s, olt, ont, "odf_for_business_ont")
        s.commit()
        provision_device(s, olt)
        provision_device(s, ont)
        s.refresh(ont)
        assert ont.provisioned is True


def test_aon_cpe_without_switch_path_cannot_be_provisioned():
    with Session(engine) as s:
        cpe = _dev("aon_cpe_no_path", DeviceType.AON_CPE)
        s.add(cpe)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, cpe)
        assert e.value.status_code == 400
        assert (
            e.value.detail
            == "Cannot provision AON_CPE: upstream AON_SWITCH is missing or not provisioned."
        )
        s.refresh(cpe)
        assert cpe.provisioned is False


def test_aon_cpe_path_to_unprovisioned_switch_cannot_be_provisioned():
    with Session(engine) as s:
        sw = _dev("aon_unprovisioned_parent", DeviceType.AON_SWITCH)
        cpe = _dev("aon_cpe_waiting_for_parent", DeviceType.AON_CPE)
        s.add(sw)
        s.add(cpe)
        s.flush()
        _connect(s, sw, cpe, "access0", "eth0")
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, cpe)
        assert e.value.status_code == 400
        assert (
            e.value.detail
            == "Cannot provision AON_CPE: upstream AON_SWITCH is missing or not provisioned."
        )
        s.refresh(cpe)
        assert cpe.provisioned is False


def test_aon_cpe_with_valid_provisioned_switch_path_can_be_provisioned():
    with Session(engine) as s:
        core = _dev("core_for_aon_parent", DeviceType.CORE_ROUTER)
        sw = _dev("aon_provisioned_parent", DeviceType.AON_SWITCH)
        cpe = _dev("aon_cpe_with_parent_path", DeviceType.AON_CPE)
        s.add(core)
        s.add(sw)
        s.add(cpe)
        s.flush()
        _connect(s, core, sw, "if0", "uplink0")
        _connect(s, sw, cpe, "access0", "eth0")
        s.commit()
        provision_device(s, sw)
        provision_device(s, cpe)
        s.refresh(cpe)
        assert cpe.provisioned is True


def test_device_creation_allowed_when_provisioning_dependency_missing():
    client = TestClient(app)
    created = client.post(
        "/api/devices",
        json={"id": "created_unwired_ont", "name": "created_unwired_ont", "type": "ONT"},
    )
    assert created.status_code == 201

    failed = client.post("/api/devices/created_unwired_ont/provision")
    assert failed.status_code == 400
    assert failed.json()["detail"] == "Cannot provision ONT: no valid provisioned OLT path found."

    with Session(engine) as s:
        stored = s.get(Device, "created_unwired_ont")
        assert stored is not None
        assert stored.provisioned is False


def test_unexpected_parent_rejected():
    """Core Router should not accept a parent container id."""
    with Session(engine) as s:
        pop = _dev("pop2", DeviceType.POP)
        core = Device(
            id="core_with_parent",
            name="core_with_parent",
            type=DeviceType.CORE_ROUTER,
            parent_container_id="pop2",
        )
        s.add(pop)
        s.add(core)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, core)
        assert e.value.status_code == 400
        assert e.value.detail.startswith("INVALID_PROVISION_PATH")


def test_aon_switch_missing_parent_optional():
    """AON Switch without parent is allowed; validate only upstream dependency."""
    with Session(engine) as s:
        core = _dev("core_for_aon", DeviceType.CORE_ROUTER)
        sw = _dev("aon_no_parent", DeviceType.AON_SWITCH)
        s.add(core)
        s.add(sw)
        s.commit()
        s.add(Interface(id=f"{core.id}-if0", device_id=core.id, name="if0"))
        s.add(Interface(id=f"{sw.id}-if0", device_id=sw.id, name="if0"))
        s.add(
            Link(
                id=f"{core.id}-{sw.id}",
                a_interface_id=f"{core.id}-if0",
                b_interface_id=f"{sw.id}-if0",
                kind=LinkType.FIBER,
            )
        )
        s.commit()
        provision_device(s, sw)
        s.commit()
        s.refresh(sw)
        assert sw.provisioned is True


def test_aon_switch_wrong_parent_type():
    """AON Switch with non-POP parent should fail."""
    with Session(engine) as s:
        core_parent = _dev("core_parent2", DeviceType.CORE_ROUTER)
        aon = Device(
            id="aon_wrong_parent",
            name="aon_wrong_parent",
            type=DeviceType.AON_SWITCH,
            parent_container_id="core_parent2",
        )
        # prerequisite separate core for dependency
        core_dep = _dev("core_dep", DeviceType.CORE_ROUTER)
        s.add(core_parent)
        s.add(core_dep)
        s.add(aon)
        s.commit()
        with pytest.raises(HTTPException) as e:
            provision_device(s, aon)
        assert e.value.status_code == 422
        assert "expected parent DeviceType.POP" in e.value.detail


def test_aon_switch_positive_case():
    """AON Switch with valid POP parent provisions successfully."""
    with Session(engine) as s:
        pop = _dev("pop_sw", DeviceType.POP)
        core = _dev("core_for_sw", DeviceType.CORE_ROUTER)
        sw = Device(
            id="aon_ok",
            name="aon_ok",
            type=DeviceType.AON_SWITCH,
            parent_container_id="pop_sw",
        )
        s.add(pop)
        s.add(core)
        s.add(sw)
        s.commit()
        # Add minimal interfaces and a logical adjacency core<->switch
        s.add(Interface(id=f"{core.id}-if0", device_id=core.id, name="if0"))
        s.add(Interface(id=f"{sw.id}-if0", device_id=sw.id, name="if0"))
        s.add(
            Link(
                id=f"{core.id}-{sw.id}",
                a_interface_id=f"{core.id}-if0",
                b_interface_id=f"{sw.id}-if0",
                kind=LinkType.FIBER,
            )
        )
        s.commit()
        provision_device(s, sw)
        s.commit()
        s.refresh(sw)
        assert sw.provisioned is True
