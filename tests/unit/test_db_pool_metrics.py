"""Unit tests for the DB pool Prometheus collector (D-25).

The pool reached no metric at all before this: exhaustion was invisible until a
request waited out ``pool_timeout`` and 500'd, and the Postgres-side alert
(``pg_stat_activity_count / pg_settings_max_connections``) can read 40% while an
individual API worker's pool is completely full.

These tests pin the two properties that make the gauges trustworthy: they
report the pool's real numbers, and a broken read degrades to "no samples"
rather than breaking the whole /metrics response.
"""

from __future__ import annotations

from app.shared.core.db_pool_metrics import DBPoolCollector

_EXPECTED_GAUGES = {
    "jaot_db_pool_size",
    "jaot_db_pool_checked_out",
    "jaot_db_pool_available",
    "jaot_db_pool_overflow",
    "jaot_db_pool_overflow_max",
    "jaot_db_pool_capacity",
}


def test_collector_yields_every_pool_gauge() -> None:
    """All six gauges are emitted, each with exactly one sample."""
    families = {f.name: f for f in DBPoolCollector().collect()}

    assert set(families) == _EXPECTED_GAUGES

    for name, family in families.items():
        assert len(family.samples) == 1, f"{name} should carry exactly one sample"
        assert family.documentation, f"{name} has no help text"


def test_capacity_is_size_plus_overflow() -> None:
    """# CONTRACT-TEST: capacity is the ceiling the saturation alert divides by.

    ApiDbPoolSaturated fires on checked_out / capacity > 0.90. If capacity ever
    stopped meaning "pool_size + max_overflow", the alert would silently move.
    """
    families = {f.name: f for f in DBPoolCollector().collect()}

    size = families["jaot_db_pool_size"].samples[0].value
    max_overflow = families["jaot_db_pool_overflow_max"].samples[0].value
    capacity = families["jaot_db_pool_capacity"].samples[0].value

    assert capacity == size + max_overflow


def test_checked_out_reflects_a_real_connection() -> None:
    """Holding a connection shows up, and returning it brings the gauge back down.

    Without this the gauge could report a constant zero and every alert built on
    it would be decorative.

    Note it checks out from ``app.shared.db.session.engine`` explicitly rather
    than using the ``db_session`` fixture: the fixture runs on the test
    harness's own engine (SAVEPOINT pattern), whose pool this collector does not
    — and should not — observe.
    """
    from sqlalchemy import text

    from app.shared.db.session import engine

    def _checked_out() -> float:
        families = {f.name: f for f in DBPoolCollector().collect()}
        return families["jaot_db_pool_checked_out"].samples[0].value

    before = _checked_out()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        during = _checked_out()

    after = _checked_out()

    assert during == before + 1, (
        f"holding one connection should raise checked_out from {before} to "
        f"{before + 1}, but the gauge reports {during}"
    )
    assert after == before, (
        f"returning the connection should restore checked_out to {before}, "
        f"but the gauge reports {after}"
    )


def test_overflow_never_reports_negative() -> None:
    """SQLAlchemy's overflow() is negative before the pool grows; we report 0.

    A negative overflow would make dashboards nonsensical and could underflow
    any expression that sums it.
    """
    families = {f.name: f for f in DBPoolCollector().collect()}

    assert families["jaot_db_pool_overflow"].samples[0].value >= 0


def test_read_failure_yields_nothing_instead_of_raising(monkeypatch) -> None:
    """# CONTRACT-TEST: a failing pool read must not break /metrics.

    An exception inside collect() takes down the entire scrape — every other
    metric on the endpoint disappears, including the alerts that would tell an
    operator what is happening.
    """
    import app.shared.db.session as session_mod

    class _ExplodingEngine:
        @property
        def pool(self):
            raise RuntimeError("pool is gone")

    monkeypatch.setattr(session_mod, "engine", _ExplodingEngine())

    assert list(DBPoolCollector().collect()) == []


def test_register_is_idempotent() -> None:
    """create_app() runs many times in the suite; double registration must not raise."""
    from app.shared.core.db_pool_metrics import register_db_pool_collector

    register_db_pool_collector()
    register_db_pool_collector()
