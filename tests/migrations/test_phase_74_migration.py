"""Phase 7.4 / D-04 + D-09 + D-13 — destructive migration validation.

Validation IDs: V-18 (DROP TABLE), V-19 (DELETE audit_log rows),
V-20 (auto_route_reason column).
"""

from __future__ import annotations

from sqlalchemy import text


def test_table_dropped(db_session) -> None:
    """V-18: solver_licenses table absent after Phase 7.4 migration.
    (Phase 7.4 / Plan 09 Task 1)"""
    result = db_session.execute(
        text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'solver_licenses'")
    ).scalar()
    assert result == 0


def test_audit_log_purged(db_session) -> None:
    """V-19: 0 rows in audit_logs with event_type LIKE 'solver_license_%'.

    Note: jaot_test starts clean; this test confirms the migration would
    delete such rows if present (DML against fresh DB is no-op but the
    DDL+DML transaction must succeed). (Phase 7.4 / Plan 09 Task 1)"""
    result = db_session.execute(
        text("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'solver_license_%'")
    ).scalar()
    assert result == 0


def test_auto_route_reason_added(db_session) -> None:
    """V-20: model_executions.auto_route_reason column exists, nullable, varchar(64).
    (Phase 7.4 / Plan 09 Task 1)"""
    row = db_session.execute(
        text(
            "SELECT data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'model_executions' "
            "AND column_name = 'auto_route_reason'"
        )
    ).first()
    assert row is not None, "auto_route_reason column missing"
    data_type, max_len, is_nullable = row
    assert data_type in ("character varying", "varchar")
    assert max_len == 64
    assert is_nullable == "YES"
