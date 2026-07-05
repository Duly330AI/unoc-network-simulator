#!/usr/bin/env python3
"""Test Go Optical Service directly."""

import asyncio

from backend.clients.go_services.optical_client import OpticalClient


async def test_optical_service():
    client = OpticalClient()

    # Test with known ONT IDs
    ont_ids = ["ont", "ont_1"]

    print(f"🔍 Testing Go Optical Service with ONTs: {ont_ids}")

    try:
        # Call Go service
        result = await asyncio.to_thread(client.recompute_paths, ont_ids)

        print("\n✅ Go Service Response:")
        print(f"  Type: {type(result)}")
        print(f"  Keys: {result.keys() if isinstance(result, dict) else 'NOT A DICT'}")

        for ont_id in ont_ids:
            path_data = result.get(ont_id)
            print(f"\n📊 ONT: {ont_id}")
            if path_data:
                print(f"  OLT ID: {path_data.get('olt_id')}")
                print(f"  Segments: {len(path_data.get('segments', []))}")
                for i, seg in enumerate(path_data.get("segments", [])):
                    print(f"    Seg {i}: {seg.get('src')} → {seg.get('dst')}")
            else:
                print("  ❌ No path data returned")

    except Exception as e:
        print(f"\n❌ Go Service Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_optical_service())
