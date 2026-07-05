"""Initialize PostgreSQL for Go integration tests."""

import os

# Set environment before imports
os.environ["DATABASE_URL"] = "postgresql://unoc:unocpw@localhost:5432/unocdb"
os.environ["UNOC_PERSISTENCE"] = "postgres"

from backend.db import get_session, reset_db
from backend.services.seed_service import ensure_default_hardware_models, ensure_physical_media

# Reset schema
print("Creating schema...")
reset_db()

# Seed catalog
print("Seeding catalog...")
with get_session() as session:
    ensure_physical_media(session)
    ensure_default_hardware_models(session)
    session.commit()

print("✅ PostgreSQL ready for tests!")
