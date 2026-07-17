"""Startup settings self-heal — idempotent and race-safe (C3, v3.1).

The API boots several uvicorn workers at once and each runs
``_ensure_settings_seeded``. The old check-then-insert made 3-of-4 workers fail
the ``platform_settings`` primary key with ``UniqueViolation`` on first boot.
The seed now inserts with ``ON CONFLICT DO NOTHING``, so a concurrent (or simply
repeated) seed is a harmless no-op instead of a crash-and-log.
"""

import pytest
from sqlalchemy.orm import Session

from app.main import _ensure_settings_seeded
from app.models.platform_setting import PlatformSetting

pytestmark = pytest.mark.contract

_KEY = "MAINTENANCE_MODE"  # stable, always-seeded registry key (default "false")


def _rows(db: Session, key: str) -> list[PlatformSetting]:
    return db.query(PlatformSetting).filter(PlatformSetting.key == key).all()


# CONTRACT-TEST: seeding a missing setting twice re-inserts it once and never
# raises — the property that makes concurrent worker boots safe.
def test_seed_is_idempotent_and_reinserts_missing(
    client,  # app fixture → SessionLocal bound to the test engine
    db_session: Session,
):
    # Drop the key so the seed has genuine work to do (exercises the INSERT).
    db_session.query(PlatformSetting).filter(PlatformSetting.key == _KEY).delete()
    db_session.commit()
    assert _rows(db_session, _KEY) == []

    _ensure_settings_seeded()  # first worker: inserts the missing key
    _ensure_settings_seeded()  # second worker: ON CONFLICT DO NOTHING, no crash

    rows = _rows(db_session, _KEY)
    assert len(rows) == 1, "exactly one row after repeated seeding (no duplicate, no crash)"
    assert rows[0].value == "false"
