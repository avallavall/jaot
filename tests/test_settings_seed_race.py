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


# CONTRACT-TEST: readonly settings mirror code constants — an upgrade must refresh
# their DB rows to the new registry default (the insert only covers MISSING keys,
# so without the refresh the admin panel would show the OLD app version forever).
def test_seed_refreshes_stale_readonly_settings(
    client,
    db_session: Session,
):
    from app.version import APP_VERSION

    db_session.query(PlatformSetting).filter(PlatformSetting.key == "APP_VERSION").delete()
    db_session.add(PlatformSetting(key="APP_VERSION", value="0.0.0-stale", updated_by="test"))
    # An admin-tuned (non-readonly) value must survive the seed untouched.
    db_session.query(PlatformSetting).filter(PlatformSetting.key == _KEY).update(
        {"value": "true", "updated_by": "admin"}
    )
    db_session.commit()

    _ensure_settings_seeded()

    (row,) = _rows(db_session, "APP_VERSION")
    db_session.refresh(row)
    assert row.value == APP_VERSION, "readonly setting must track the code constant"
    assert row.updated_by == "system_seed"

    tuned = _rows(db_session, _KEY)[0]
    db_session.refresh(tuned)
    assert tuned.value == "true", "the seed must never clobber an admin-tuned setting"
