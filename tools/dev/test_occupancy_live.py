"""Test PON occupancy live from running backend."""

import requests

# Test OLT
response = requests.get("http://localhost:5001/api/ports/summary/olt")
if response.status_code == 200:
    data = response.json()
    print(f"\n📊 OLT Port Summary ({len(data)} interfaces):")
    for iface in data:
        if iface.get("port_role") == "PON":
            occ = iface.get("occupancy", 0)
            print(f"  - {iface['name']}: occupancy={occ}, status={iface.get('effective_status')}")
else:
    print(f"❌ OLT request failed: {response.status_code} {response.text}")

# Test AON Switch
response = requests.get("http://localhost:5001/api/ports/summary/aon_switch")
if response.status_code == 200:
    data = response.json()
    print(f"\n📊 AON Switch Port Summary ({len(data)} interfaces):")
    for iface in data:
        if iface.get("port_role") == "ACCESS":
            occ = iface.get("occupancy", 0)
            print(f"  - {iface['name']}: occupancy={occ}, status={iface.get('effective_status')}")
else:
    print(f"❌ AON Switch request failed: {response.status_code} {response.text}")
