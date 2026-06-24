#!/usr/bin/env python3
"""
One-shot dev seed: migrations + admin + normal user + catalog templates.

Usage (local):
    python scripts/seed_dev.py

Usage (docker):
    docker-compose --profile seed run --rm seed
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_step(description: str, args: list[str]) -> None:
    print(f"\n{'='*48}")
    print(f"  {description}")
    print(f"{'='*48}")
    result = subprocess.run(args, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"FAILED: {description}")
        sys.exit(result.returncode)


def main() -> None:
    print("JAOT dev seed — full database bootstrap")

    run_step("Running migrations (alembic upgrade head)", [sys.executable, "-m", "alembic", "-c", "infra/alembic.ini", "upgrade", "head"])

    run_step("Creating admin user", [sys.executable, str(PROJECT_ROOT / "scripts" / "ensure_admin_api_key.py")])

    run_step("Creating normal user", [sys.executable, str(PROJECT_ROOT / "scripts" / "ensure_normal_user.py")])

    # App lifespan seeds these too; run explicitly to be safe.
    print(f"\n{'='*48}")
    print("  Seeding model catalog templates")
    print(f"{'='*48}")
    from app.shared.db.seed_models import seed_official_models
    from app.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        count = seed_official_models(db)
        db.commit()
        print(f"Seeded {count} catalog templates")
    finally:
        db.close()

    print(f"\n{'='*48}")
    print("  All done! Database is ready for development.")
    print(f"{'='*48}\n")


if __name__ == "__main__":
    main()
