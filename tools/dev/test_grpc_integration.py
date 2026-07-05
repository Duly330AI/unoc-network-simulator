#!/usr/bin/env python3
"""
Week 1 Day 4: Integration Test for Go gRPC Services

Tests:
1. Python protobuf stub imports
2. gRPC client connection (with fallback)
3. Health check simulation
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_protobuf_imports():
    """Test that generated protobuf stubs can be imported."""
    print("🧪 Test 1: Protobuf Stub Imports")
    print("-" * 50)

    try:
        from backend.proto import optical_pb2, optical_pb2_grpc

        print("✅ Optical stubs: OK")

        from backend.proto import batch_pb2, batch_pb2_grpc

        print("✅ Batch stubs: OK")

        from backend.proto import status_pb2, status_pb2_grpc

        print("✅ Status stubs: OK")

        print("✅ All protobuf imports successful!\n")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}\n")
        return False


def test_client_creation():
    """Test that gRPC clients can be created (will use fallback if Go not running)."""
    print("🧪 Test 2: gRPC Client Creation")
    print("-" * 50)

    try:
        from backend.clients.go_services import (
            get_batch_client,
            get_optical_client,
            get_status_client,
        )

        # Create clients (will fallback to Python if Go not running)
        optical = get_optical_client()
        print(f"✅ Optical client created (Go available: {optical._go_available})")

        batch = get_batch_client()
        print(f"✅ Batch client created (Go available: {batch._go_available})")

        status = get_status_client()
        print(f"✅ Status client created (Go available: {status._go_available})")

        if not (optical._go_available or batch._go_available or status._go_available):
            print("\n⚠️  Note: All clients using Python fallback (Go services not running)")
            print("   This is OK for Week 1 - services will be started in Week 2")

        print("✅ All clients created successfully!\n")
        return True
    except Exception as e:
        print(f"❌ Client creation failed: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_health_check_simulation():
    """Test health check method (will fallback if Go not running)."""
    print("🧪 Test 3: Health Check Simulation")
    print("-" * 50)

    try:
        from backend.clients.go_services import get_optical_client

        optical = get_optical_client()
        health = optical.health()

        print(f"Health Response: {health}")
        print(f"Backend: {health['backend']}")
        print(f"Available: {health['available']}")

        print("✅ Health check simulation successful!\n")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all integration tests."""
    print("=" * 50)
    print("Week 1 Day 4: Go gRPC Integration Test")
    print("=" * 50)
    print()

    tests = [
        ("Protobuf Imports", test_protobuf_imports),
        ("Client Creation", test_client_creation),
        ("Health Check", test_health_check_simulation),
    ]

    results = []
    for name, test_func in tests:
        result = test_func()
        results.append((name, result))

    print("=" * 50)
    print("Test Summary")
    print("=" * 50)
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    all_passed = all(r for _, r in results)
    print()
    if all_passed:
        print("🎉 All tests passed! Week 1 Day 4 integration successful.")
        print()
        print("Next Steps:")
        print(
            "1. Start Go services (Week 2): bin/optical-service.exe, bin/batch-service.exe, bin/status-service.exe"
        )
        print("2. Verify Go services respond to health checks")
        print("3. Implement actual gRPC methods in Week 2")
        return 0
    else:
        print("❌ Some tests failed. Check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
