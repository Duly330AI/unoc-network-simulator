#!/usr/bin/env python
"""Quick test to verify schema creation in inmemory mode."""
import os

os.environ["UNOC_PERSISTENCE"] = "inmemory"
os.environ["DATABASE_URL"] = ""
os.environ["UNOC_DB_URL"] = ""

from sqlalchemy import text

import backend.db as db

print("=== Testing schema creation in inmemory mode ===")
print(f"URL: {db.SQLALCHEMY_DATABASE_URL}")
print(f"Persistence mode: {os.getenv('UNOC_PERSISTENCE')}")

print("\n1. Calling reset_db()...")
db.reset_db()

print("2. Calling init_db()...")
db.init_db()

print("3. Checking tables with sync engine...")
with db.engine.connect() as conn:
    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    tables = [r[0] for r in result]
    print(f"   Tables found: {tables}")

if "device" in tables:
    print("\n✅ SUCCESS: 'device' table exists!")
    print("4. Testing a simple query...")
    with db.engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM device"))
        count = result.scalar()
        print(f"   Device count: {count}")
else:
    print("\n❌ FAILURE: 'device' table NOT found!")
    print(f"   Only found: {tables}")
