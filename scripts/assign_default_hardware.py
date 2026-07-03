"""Assign default hardware models to existing devices that have none.

Devices created while AUTO_ASSIGN_DEFAULT_HARDWARE was off have
hardware_model_id=NULL and fall back to the per-type capacity defaults in
catalog_effective.py (e.g. EDGE_ROUTER 10 Gbps instead of the catalog's
DEFAULT_EDGE_ROUTER 200 Gbps). This script reconciles them via the regular
device update API, which also auto-provisions interfaces from the model's
port profiles.

Usage:
    python scripts/assign_default_hardware.py            # dry-run (default)
    python scripts/assign_default_hardware.py --apply    # write changes
    python scripts/assign_default_hardware.py --base-url http://127.0.0.1:5001
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def http_json(method: str, url: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else None


def pick_default_model(models: list[dict]) -> dict | None:
    """Mirror backend auto-assign: prefer seeded defaults, else first model."""
    for m in models:
        if str(m.get("catalog_id", "")).startswith("DEFAULT_"):
            return m
    return models[0] if models else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    _, devices = http_json("GET", f"{base}/api/devices")
    _, catalog = http_json("GET", f"{base}/api/catalog/hardware")

    by_type: dict[str, list[dict]] = {}
    for m in catalog or []:
        by_type.setdefault(str(m.get("device_type")), []).append(m)

    candidates = [d for d in devices or [] if d.get("hardware_model_id") is None]
    print(f"Devices ohne Hardwaremodell: {len(candidates)} von {len(devices or [])}")

    changed = 0
    skipped = 0
    failed = 0
    for d in candidates:
        dtype = str(d.get("type"))
        model = pick_default_model(by_type.get(dtype, []))
        if not model:
            print(f"  SKIP {d['id']} ({dtype}): kein Katalogmodell für diesen Typ")
            skipped += 1
            continue
        label = f"{d['id']} ({dtype}) -> {model.get('catalog_id')} (id={model.get('id')})"
        if not args.apply:
            print(f"  DRY-RUN {label}")
            changed += 1
            continue
        try:
            status, _ = http_json(
                "PUT", f"{base}/api/devices/{d['id']}", {"hardware_model_id": model["id"]}
            )
            print(f"  OK [{status}] {label}")
            changed += 1
        except urllib.error.HTTPError as e:
            print(f"  FAIL {label}: HTTP {e.code} {e.read().decode('utf-8')[:200]}")
            failed += 1

    mode = "angewendet" if args.apply else "dry-run (nichts geschrieben; --apply zum Ausführen)"
    print(f"Fertig: {changed} zugewiesen, {skipped} übersprungen, {failed} fehlgeschlagen — {mode}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
