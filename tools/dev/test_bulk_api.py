#!/usr/bin/env python3
"""Test BULK API endpoint (wie Frontend es aufruft)."""

import json

import requests

print("=" * 80)
print("TESTING BULK API (wie Frontend)")
print("=" * 80)

try:
    # BULK API: /api/ports/summary?ids=olt&ids=aon_switch
    url = "http://localhost:5001/api/ports/summary?ids=olt&ids=aon_switch"
    print(f"\nURL: {url}")

    r = requests.get(url)
    print(f"Status: {r.status_code}")
    r.raise_for_status()

    data = r.json()
    print(f"\nResponse type: {type(data)}")
    print(f"Keys: {list(data.keys())}")

    # Check OLT data
    if "olt" in data:
        olt_data = data["olt"]
        print(f"\n>>> OLT: {len(olt_data)} interfaces")
        pon_ports = [p for p in olt_data if p.get("port_role") == "PON"]
        print(f"    PON ports: {len(pon_ports)}")
        if pon_ports:
            total_onts = sum(int(p.get("occupancy", 0) or 0) for p in pon_ports)
            print(f"    Total ONTs: {total_onts}")
            print(
                f"    First PON: {pon_ports[0].get('name')}, occupancy={pon_ports[0].get('occupancy')}"
            )
    else:
        print("\n>>> ERROR: No 'olt' key in response!")

    # Check AON_SWITCH data
    if "aon_switch" in data:
        aon_data = data["aon_switch"]
        print(f"\n>>> AON_SWITCH: {len(aon_data)} interfaces")
        access_ports = [p for p in aon_data if p.get("port_role") == "ACCESS"]
        print(f"    ACCESS ports: {len(access_ports)}")
        if access_ports:
            total_cpes = sum(int(p.get("occupancy", 0) or 0) for p in access_ports)
            print(f"    Total CPEs: {total_cpes}")
            print(
                f"    First ACCESS: {access_ports[0].get('name')}, occupancy={access_ports[0].get('occupancy')}"
            )
    else:
        print("\n>>> ERROR: No 'aon_switch' key in response!")

    # Print full response for debugging
    print("\n" + "=" * 80)
    print("FULL RESPONSE:")
    print(json.dumps(data, indent=2))

except Exception as e:
    print(f"ERROR: {e}")
    import traceback

    traceback.print_exc()
