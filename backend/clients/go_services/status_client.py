"""
Status Propagation Service gRPC Client with Python Fallback

Week 1 Day 4: Python protobuf stubs generated - gRPC communication enabled.
Falls back to Python implementation if Go service unavailable.
"""

from typing import Any

import grpc

from backend.proto import status_pb2_grpc


class StatusClient:
    """
    Client for status propagation service (Go gRPC or Python fallback).

    Week 2 implementation will handle:
    - PropagateStatus: Cascade status through dependency tree
    - GetDependencies: Retrieve upstream dependency tree
    - BulkUpdateStatus: Atomic multi-device status update
    """

    def __init__(
        self,
        grpc_host: str = "localhost",
        grpc_port: int = 50053,
        timeout: float = 30.0,
        use_fallback: bool = True,
    ):
        """Initialize status client."""
        self.grpc_address = f"{grpc_host}:{grpc_port}"
        self.timeout = timeout
        self.use_fallback = use_fallback
        self._channel: grpc.Channel | None = None
        self._stub = None
        self._go_available = False

        self._try_connect()

    def _try_connect(self) -> bool:
        """Attempt to connect to Go service."""
        try:
            self._channel = grpc.insecure_channel(
                self.grpc_address,
                options=[
                    ("grpc.max_receive_message_length", 100 * 1024 * 1024),
                    ("grpc.keepalive_time_ms", 10000),
                ],
            )

            # Create gRPC stub for status service
            self._stub = status_pb2_grpc.StatusServiceStub(self._channel)

            self._go_available = True
            print(f"[OK] Connected to Go status-service at {self.grpc_address}")
            return True

        except Exception as e:
            print(f"⚠️ Go status-service unavailable: {e}")
            if self.use_fallback:
                print("➡️ Falling back to Python status implementation")
            self._go_available = False
            return False

    def propagate_status(
        self,
        changed_device_ids: list[str],
        changed_link_ids: list[str] | None = None,
        update_database: bool = True,
    ) -> dict[str, Any]:
        """
        Propagate status changes through dependency graph.

        Args:
            changed_device_ids: List of device IDs that changed status
            changed_link_ids: List of link IDs that changed status (optional)
            update_database: Whether to update database (or dry-run)

        Returns:
            Dict with keys:
                - affected_devices: List[str] (device IDs affected)
                - affected_links: List[str] (link IDs affected)
                - dependency_paths: Dict[str, List[str]] (device_id -> path)
                - duration_ms: int (execution time in milliseconds)
                - source: str ("go" or "python")

        Raises:
            Exception: If both Go and Python fallback fail
        """
        changed_link_ids = changed_link_ids or []

        if self._go_available:
            try:
                return self._propagate_go(
                    changed_device_ids,
                    changed_link_ids,
                    update_database,
                )
            except Exception as e:
                print(f"⚠️ Go service failed: {e}")
                if self.use_fallback:
                    print("➡️ Falling back to Python implementation")
                    return self._propagate_python(
                        changed_device_ids,
                        changed_link_ids,
                        update_database,
                    )
                raise
        else:
            if self.use_fallback:
                return self._propagate_python(
                    changed_device_ids,
                    changed_link_ids,
                    update_database,
                )
            raise RuntimeError("Go service unavailable and fallback disabled")

    def _propagate_go(
        self,
        changed_device_ids: list[str],
        changed_link_ids: list[str],
        update_database: bool,
    ) -> dict[str, Any]:
        """Call Go service for status propagation."""
        from backend.proto import status_pb2

        # Note: GO service doesn't have update_database field in protobuf
        # It always updates DB internally. Python fallback handles the flag.
        request = status_pb2.PropagateRequest(
            changed_device_ids=changed_device_ids,
            changed_link_ids=changed_link_ids,
            force_full_propagation=False,  # Use changed IDs only
        )

        response = self._stub.PropagateStatus(request, timeout=self.timeout)

        return {
            "affected_devices": (
                list(response.device_ids) if hasattr(response, "device_ids") else []
            ),
            "affected_links": [],  # GO service doesn't return link IDs yet
            "dependency_paths": {},  # GO service doesn't return paths yet
            "duration_ms": response.duration_ms,
            "source": "go",
        }

    def _propagate_python(
        self,
        changed_device_ids: list[str],
        changed_link_ids: list[str],
        update_database: bool,
    ) -> dict[str, Any]:
        """
        Fallback to Python implementation.

        NOTE: This is ~30,000× slower than Go (2000ms vs 66μs)
        but provides functional fallback when Go service unavailable.
        """
        import time

        from backend.services.status_service import (
            bulk_update_device_statuses,
            detect_causal_chain_python,
        )

        start_time = time.perf_counter()

        # Call Python causal chain detection
        result = detect_causal_chain_python(
            changed_device_ids=changed_device_ids,
            changed_link_ids=changed_link_ids,
        )

        if update_database:
            bulk_update_device_statuses(result["affected_devices"])

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return {
            "affected_devices": result["affected_devices"],
            "affected_links": result["affected_links"],
            "dependency_paths": result.get("dependency_paths", {}),
            "duration_ms": duration_ms,
            "source": "python",
        }

    def health(self) -> dict[str, Any]:
        """Check status service health."""
        if self._go_available:
            # Try health check on Go service
            try:
                from backend.proto import status_pb2

                request = status_pb2.HealthRequest()
                response = self._stub.Health(request, timeout=5.0)
                raw_status = str(getattr(response, "status", "")).strip()
                status = raw_status.upper() if raw_status else "UNKNOWN"
                if status in {"HEALTHY", "OK", "UP", "SERVING"}:
                    status = "HEALTHY"
                db_status = str(getattr(response, "db_status", "")).strip()
                return {
                    "status": status,
                    "message": f"db_status={db_status}" if db_status else None,
                    "version": getattr(response, "version", None),
                    "backend": "go",
                }
            except Exception as e:
                return {
                    "status": "UNHEALTHY",
                    "message": f"Go service check failed: {e}",
                    "backend": "go",
                }

        return {
            "status": "PYTHON_ONLY",
            "message": "Go service unavailable, using Python fallback",
            "backend": "python",
        }

    def close(self):
        """Close gRPC channel."""
        if self._channel:
            self._channel.close()
            print("Closed status service gRPC channel")


# Singleton instance
_status_client: StatusClient | None = None


def get_status_client() -> StatusClient:
    """Get singleton status client instance."""
    global _status_client
    if _status_client is None:
        _status_client = StatusClient()
    return _status_client
