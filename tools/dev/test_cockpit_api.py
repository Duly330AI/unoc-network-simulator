#!/usr/bin/env python3
"""Test what the cockpits ACTUALLY receive from backend API."""


import requests

print("=" * 80)
print("TESTING OLT COCKPIT DATA")
print("=" * 80)

try:
    r = requests.get("http://localhost:5001/api/ports/summary/olt")
    r.raise_for_status()
    data = r.json()

    print(f"\nTotal interfaces: {len(data)}")

    pon_ports = [p for p in data if p.get("port_role") == "PON"]
    print(f"PON ports: {len(pon_ports)}")

    print("\nFirst 3 PON ports:")
    for p in pon_ports[:3]:
        occ = p.get("occupancy", "MISSING")
        name = p.get("name", "NONAME")
        status = p.get("effective_status", "NOSTATUS")
        print(f"  {name}: occupancy={occ}, status={status}")

    # Check total ONTs
    total_onts = sum(int(p.get("occupancy", 0) or 0) for p in pon_ports)
    print(f"\n>>> TOTAL ONTs across all PON ports: {total_onts}")

except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 80)
print("TESTING AON_SWITCH COCKPIT DATA")
print("=" * 80)

try:
    r = requests.get("http://localhost:5001/api/ports/summary/aon_switch")
    r.raise_for_status()
    data = r.json()

    print(f"\nTotal interfaces: {len(data)}")

    access_ports = [p for p in data if p.get("port_role") == "ACCESS"]
    print(f"ACCESS ports: {len(access_ports)}")

    print("\nFirst 3 ACCESS ports:")
    for p in access_ports[:3]:
        occ = p.get("occupancy", "MISSING")
        name = p.get("name", "NONAME")
        status = p.get("effective_status", "NOSTATUS")
        print(f"  {name}: occupancy={occ}, status={status}")

    # Check total CPEs
    total_cpes = sum(int(p.get("occupancy", 0) or 0) for p in access_ports)
    print(f"\n>>> TOTAL CPEs across all ACCESS ports: {total_cpes}")

except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 80)
