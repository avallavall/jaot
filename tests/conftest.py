"""Pytest configuration and fixtures.

All tests run against real PostgreSQL (jaot_test database, auto-created).

Architecture:
  - ONE engine (db_engine) for the entire session.
  - All application code (middleware, endpoints, lifespan) is redirected to use
    this engine via module-level overrides of app.db.session.
  - Each test gets a fresh Session with TRUNCATE cleanup after.
  - Auth middleware creates sessions from the same engine pool.
  - Test data must be committed (not just flushed) for middleware to see it.
"""

import atexit
import os
import signal
from datetime import timedelta

# Environment setup — MUST happen before any app imports
DEFAULT_TEST_DB_URL = "postgresql://jaot:jaot@localhost:5432/jaot_test"
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = _TEST_DB_URL
if not os.environ.get("JWT_SECRET"):
    os.environ["JWT_SECRET"] = "test-jwt-secret-for-pytest-only"

# Now safe to import app modules
# Load the real rate_limiter module FIRST so its sys.modules self-alias
# (`sys.modules["app.core.rate_limiter"] = sys.modules[__name__]`) is in
# place before any test file's top-level `from app.core.rate_limiter
# import ...` runs at collection time. Without this, tests that import
# via the shim path capture stale function objects whose `__globals__`
# point at the placeholder shim module, and fixture mutations of the
# real module's state (e.g. `_bypass`, `_force_real`) are invisible.
import app.shared.core.rate_limiter  # noqa: E402, F401
from app.config import settings  # noqa: E402

settings.DATABASE_URL = _TEST_DB_URL

# Make prometheus-fastapi-instrumentator middleware idempotent against the global
# REGISTRY. The library creates a fresh `http_requests_inprogress` Gauge in every
# middleware __init__ without a `registry=` parameter, so it always targets the
# global REGISTRY. When pytest-randomly schedules tests so that multiple FastAPI
# apps coexist (session-scoped `app` fixture below + per-test apps in
# test_monitoring.py, test_security_cors.py, test_security_headers.py,
# tests/api/test_profiles.py, tests/mcp/test_mcp.py — all of which call
# `create_app()` directly), the second app's middleware stack build raises
# `ValueError: Duplicated timeseries in CollectorRegistry: {'http_requests_inprogress'}`.
# Pre-cleaning http_* collectors inside the wrapped __init__ makes registration
# idempotent: each ctor evicts any stale http_* collector before creating its
# gauge. Test-only — production has one app, one middleware stack, one gauge,
# and the shim is a no-op there.
from prometheus_client import REGISTRY as _PROM_REGISTRY_FOR_TESTS  # noqa: E402
from prometheus_fastapi_instrumentator import (  # noqa: E402
    middleware as _prom_instr_middleware,
)

_orig_prom_instr_mw_init = _prom_instr_middleware.PrometheusInstrumentatorMiddleware.__init__


def _idempotent_prom_instr_mw_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    stale = [
        c
        for name, c in list(_PROM_REGISTRY_FOR_TESTS._names_to_collectors.items())
        if name.startswith("http_")
    ]
    for c in set(stale):
        try:
            _PROM_REGISTRY_FOR_TESTS.unregister(c)
        except Exception:
            pass
    return _orig_prom_instr_mw_init(self, *args, **kwargs)


if not getattr(
    _prom_instr_middleware.PrometheusInstrumentatorMiddleware.__init__,
    "_jaot_test_idempotent_shim",
    False,
):
    _idempotent_prom_instr_mw_init._jaot_test_idempotent_shim = True  # type: ignore[attr-defined]
    _prom_instr_middleware.PrometheusInstrumentatorMiddleware.__init__ = (
        _idempotent_prom_instr_mw_init
    )

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.models import Organization, User  # noqa: E402
from app.services.auth.api_key_service import APIKeyService  # noqa: E402
from app.shared.utils.datetime_helpers import utcnow  # noqa: E402

# Override Organization rate limit column defaults for test sessions.
# Production defaults (2/min, 10/day) are absurdly low for a test suite that
# hammers the same org ID thousands of times. Patching the column default
# means ANY Organization() created without explicit rate limits inherits
# test-appropriate values. Production defaults live in the ORM model and are
# NOT affected — this only changes the Python-side default, not the DB schema.
Organization.__table__.columns["rate_limit_per_minute"].default.arg = 999_999
Organization.__table__.columns["rate_limit_per_day"].default.arg = 999_999

# All application tables for cleanup (child tables first, parents last)
_ALL_TABLES = [
    "formulation_ratings",
    "conversation_attachments",
    "llm_messages",
    "llm_conversations",
    "trigger_runs",
    "trigger_schedules",
    "solve_triggers",
    "workspace_invites",
    "workspace_members",
    "workspace_credit_pools",
    "workspaces",
    "model_version_snapshots",
    "model_builder_documents",
    "model_reviews",
    "model_executions",
    "organization_models",
    "invoices",
    "audit_logs",
    "notifications",
    "analytics_events",
    "platform_setting_audit",
    "model_view_events",
    "featured_placements",
    "verification_requests",
    "notification_preferences",
    "user_favorites",
    "recent_models",
    "platform_settings",
    "credit_transactions",
    "usage_records",
    "seller_tos_acceptances",
    "withdrawal_schedules",
    "withdrawals",
    "exchange_rates",
    "refresh_tokens",
    "api_keys",
    "users",
    "model_catalog",
    "organizations",
]


@pytest.fixture(scope="session")
def db_engine():
    """Create test engine and run migrations once per session."""
    admin_url = _TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'jaot_test'")
        ).fetchone()
        if not exists:
            conn.execute(text("CREATE DATABASE jaot_test"))
    admin_engine.dispose()

    # Kill zombie connections from previous crashed runs BEFORE creating engine.
    # Loop until all stale backends are gone — pg_terminate_backend is async,
    # the target process may take a moment to shut down.
    import time as _time

    _admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with _admin.connect() as c:
            c.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = 'jaot_test' AND pid <> pg_backend_pid()"
                )
            )
        # Wait until all other backends are actually gone
        for _attempt in range(20):
            with _admin.connect() as c:
                remaining = c.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = 'jaot_test' AND pid <> pg_backend_pid()"
                    )
                ).scalar()
            if remaining == 0:
                break
            _time.sleep(0.5)
    except Exception:
        pass
    _admin.dispose()

    # Dispose the app-level engine to drop stale pool references.
    try:
        from app.shared.db.session import engine as _app_engine

        _app_engine.dispose()
    except Exception:
        pass

    engine = create_engine(
        _TEST_DB_URL,
        echo=False,
        pool_size=30,
        max_overflow=10,
        pool_pre_ping=True,
    )

    alembic_cfg = AlembicConfig("infra/alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", _TEST_DB_URL)
    command.upgrade(alembic_cfg, "head")

    # Dispose pool after alembic migrations to get fresh connections
    engine.dispose()

    # Clean residual data from previous crashed runs using TRUNCATE CASCADE.
    # At this point no other connections exist, so AccessExclusiveLock is fine.
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE " + ", ".join(_ALL_TABLES) + " CASCADE"))
        conn.commit()

    # Verify cleanup succeeded
    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM organizations")).scalar()
        assert count == 0, f"Initial cleanup failed: {count} rows in organizations"

    import logging

    logging.getLogger(__name__).warning("INITIAL CLEANUP: organizations has 0 rows")

    atexit.register(engine.dispose)

    def _signal_handler(signum, frame):
        engine.dispose()
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app(db_engine):
    """Create FastAPI application for testing.

    Redirects ALL session/engine references to the test engine so that
    middleware, lifespan, and endpoint code all share the same connection
    pool. This prevents rogue connections from a separate engine that
    could hold locks and block TRUNCATE cleanup between tests.
    """
    import app.shared.core.auth_middleware as auth_mw
    import app.shared.core.maintenance_middleware as maint_mw
    import app.shared.db.session as db_session_mod
    from app.main import create_app

    _MiddlewareSession = sessionmaker(bind=db_engine, expire_on_commit=False)

    # Save originals
    original_auth_factory = auth_mw._session_factory
    original_maint_factory = maint_mw._session_factory
    original_engine = db_session_mod.engine
    original_session_local = db_session_mod.SessionLocal

    # Redirect everything to test engine
    auth_mw._session_factory = _MiddlewareSession
    maint_mw._session_factory = _MiddlewareSession
    maint_mw._skip_maintenance_check = True  # skip maintenance DB check in tests
    db_session_mod.engine = db_engine
    db_session_mod.SessionLocal = _MiddlewareSession

    original_engine.dispose()

    application = create_app()

    # Dispose pool after app creation (lifespan startup may create connections
    # to seed data or ensure Beat tables). Drop those connections so tests
    # start with a clean pool, avoiding stale-connection errors when the
    # previous pytest run left lingering backends that pg_terminate_backend
    # is still shutting down.
    db_engine.dispose()

    yield application

    auth_mw._session_factory = original_auth_factory
    maint_mw._session_factory = original_maint_factory
    db_session_mod.engine = original_engine
    db_session_mod.SessionLocal = original_session_local


@pytest.fixture(scope="session")
def client(app):
    """Session-scoped unauthenticated test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Per-test database session with DELETE cleanup.

    Each test gets a fresh session. After the test the session is closed
    and all rows are deleted using DELETE (not TRUNCATE) to avoid
    AccessExclusiveLock conflicts with middleware connections.
    """
    session = Session(bind=db_engine, expire_on_commit=False)

    yield session

    # Rollback any pending transaction to release locks
    try:
        session.rollback()
    except Exception:
        pass

    # Clean all tables using DELETE (child-first ordering for FK compliance).
    # We use DELETE instead of TRUNCATE because TRUNCATE acquires
    # AccessExclusiveLock which blocks on middleware idle-in-transaction
    # connections, whereas DELETE only needs RowExclusiveLock.
    try:
        for table in _ALL_TABLES:
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass

    try:
        session.close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _override_db_dependency(app, client, db_session):
    """Override get_db to return the test session for all endpoints.

    Also resets the session-scoped TestClient cookie jar around every test.
    The ``client`` fixture is session-scoped, so its underlying httpx cookie
    jar persists across the whole run. httpx automatically stores
    ``Set-Cookie`` response cookies, so any test that hits an auth endpoint
    issuing a ``jaot_access_token`` (login/signup/email flows in
    test_auth_email.py, test_security_cookies.py, etc.) leaves that cookie in
    the shared jar. The per-test DB cleanup deletes the user/org the cookie
    refers to, but the cookie itself survives. Under pytest-randomly a later
    test then sends a stale — and sometimes ``admin: true`` — cookie it never
    set.

    This was the root cause of the ``TestMaintenanceSettingToggle`` order
    coupling (2026-05-21 todo): TestLoginEmail seeds ``role="admin"`` users and
    logs them in, leaking an admin JWT cookie. The maintenance middleware then
    treated the toggle-test request as an admin bypass, fell through to the
    auth middleware — which 401s on the now-deleted user — instead of returning
    the expected 503, surfacing as ``assert 401 == 503``.

    Clearing the jar before AND after each test restores this global state to
    the suite default (empty) for every test, eliminating the leak at its
    source. Tests that deliberately exercise cookies (e.g.
    TestMaintenanceModeAdminBypass) pass them per-request via ``cookies=``,
    which is unaffected by clearing the persistent jar.
    """
    from app.shared.db.base import get_db

    if client is not None:
        client.cookies.clear()

    def _test_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _test_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    if client is not None:
        client.cookies.clear()


@pytest.fixture
def override_db_dependency(_override_db_dependency):
    """Explicit (non-autouse) alias so tests can request it by name."""
    return _override_db_dependency


@pytest.fixture(autouse=True)
def _ensure_default_adapters_registered() -> None:
    """Re-register default solver adapters before every test.

    Closes the test-order flake first observed in Phase 12.0 Plan 04 Option D
    pre-flight under pytest-randomly: `tests/unit/domains/solver/conftest.py`
    has an autouse `_reset_solver_registry` fixture that wipes the process-
    global solver registry on every setup AND teardown. When randomization
    schedules ANY test in `tests/unit/domains/solver/` BEFORE tests that need
    the registry populated (anything that resolves a solver by name through
    the registry — `/api/v2/solve`, `/api/v2/solvers/available`,
    `test_runtime_settings`, `test_platform_abuse`, etc.), those later tests
    see an empty registry and crash with `SolverNotFoundError: Solver 'scip'
    is not registered.` or `assert 422 == 200`.

    Originally introduced at `tests/integration/api/v2/conftest.py` for
    Phase 7.1 / D-7.1-14, where it only covered the v2 integration subtree
    (see 07-SIMPLIFY-2.md §Follow-up Notes: "Solver 'highs' is not
    registered" when unit tests ran first). Phase 12.0 Plan 04 Option D
    pre-flight surfaced the same flake suite-wide under pytest-randomly,
    so the guard was hoisted here and the narrower v2-scoped fixture
    deleted. Pytest fixture resolution runs parent conftest setup BEFORE
    child conftest setup, so `tests/unit/domains/solver/` tests still see
    the inner `_reset_solver_registry.setup()` wipe AFTER this top-level
    register — their own expectation (clean registry) is preserved.

    `register_default_adapters()` is idempotent (per its docstring:
    "Idempotent — calling twice re-registers (last write wins) but does not
    raise"), so this is safe and runs in ~O(ms).

    The longer-term fix is in `app/domains/solver/__init__.py` so any
    in-process registry use (not just tests) auto-bootstraps. Until then,
    this guard prevents the test-order flake from blocking the v2.3 baseline.
    """
    from app.domains.solver.adapters import register_default_adapters

    register_default_adapters()
    yield
    # No teardown — the next test re-registers. Matching the comment in
    # tests/integration/api/v2/conftest.py: calling registry.reset() here
    # would re-break the other direction (clears state unit tests expect).


@pytest.fixture(autouse=True)
def _bypass_rate_limiter():
    """Bypass rate limiting in tests to prevent cross-test contamination.

    The in-memory sliding window accumulates entries across 3000+ tests sharing
    the same TestClient IP and org ID, causing spurious 429s. `_is_bypassed()`
    in rate_limiter also returns True whenever PYTEST_CURRENT_TEST is set,
    so even if this fixture somehow fails to run (ordering, plugin issues),
    CI will still bypass by default.

    Tests that specifically verify rate limiting behavior must use the
    `real_rate_limiter` fixture to disable the bypass for their scope.
    """
    import app.shared.core.rate_limiter as rl

    rl._bypass = True
    rl._force_real = False
    rl._memory_store.clear()
    yield
    rl._bypass = True
    rl._force_real = False
    rl._memory_store.clear()


@pytest.fixture(autouse=True)
def _reset_llm_budget_cache():
    """Reset the in-process LLM budget cache around every test (W17).

    The budget gate caches (month_cost, budget) for ~60s. Without this
    reset, a test that exercises the over-budget path would poison every
    LLM send-message test running in the following 60 seconds with a 403,
    and vice versa (an under-budget cache could mask an over-budget test).
    """
    from app.services.llm.cost_tracking import reset_budget_cache

    reset_budget_cache()
    yield
    reset_budget_cache()


@pytest.fixture
def real_rate_limiter():
    """Restore real rate limiter for tests that deliberately test rate limiting.

    Usage: add `real_rate_limiter` to the test function signature.
    """
    import app.shared.core.rate_limiter as rl

    rl._bypass = False
    rl._force_real = True
    rl._memory_store.clear()
    rl.clear()
    yield
    rl._bypass = True
    rl._force_real = False
    rl._memory_store.clear()
    rl.clear()


@pytest.fixture(autouse=True)
def _seed_platform_settings(db_session):
    """Seed platform_settings with registry defaults before each test.

    The per-test DELETE cleanup removes platform_settings rows, so we
    re-seed from the registry to prevent MissingSettingError in code
    that reads settings via PlatformSettingsService.
    Uses ON CONFLICT DO NOTHING to preserve any test-specific overrides
    inserted earlier in the fixture chain.

    Skips gracefully when db_session is None (e.g. MCP tests that
    override db_session to a no-op).
    """
    if db_session is None:
        yield
        return

    from app.services.settings_registry import SETTINGS_REGISTRY

    for defn in SETTINGS_REGISTRY:
        if defn.default_value is None:
            continue
        db_session.execute(
            text(
                "INSERT INTO platform_settings "
                "(key, value, updated_at, updated_by) "
                "VALUES (:key, :value, NOW(), 'test_seed') "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": defn.key, "value": defn.default_value},
        )
    db_session.commit()
    yield


@pytest.fixture
def test_organization(db_session):
    org = Organization(
        id="org_test001",
        name="Test Company",
        credits_balance=1000,
        is_active=True,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def test_organization_2(db_session):
    org = Organization(
        id="org_test002",
        name="Another Company",
        credits_balance=500,
        is_active=True,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def test_user(db_session, test_organization):
    user = User(
        id="user_test001",
        email="test@example.com",
        name="Test User",
        organization_id=test_organization.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_user_2(db_session, test_organization_2):
    user = User(
        id="user_test002",
        email="test2@example.com",
        name="Test User 2",
        organization_id=test_organization_2.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_admin_user(db_session, test_organization):
    user = User(
        id="user_admin001",
        email="admin@example.com",
        name="Admin User",
        organization_id=test_organization.id,
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_user_non_admin(db_session, test_organization):
    user = User(
        id="user_regular001",
        email="regular@example.com",
        name="Regular User",
        organization_id=test_organization.id,
        role="member",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_api_key(db_session, test_user, test_organization):
    api_key, plaintext_key = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_user.id,
        organization_id=test_organization.id,
        name="Test Key",
        prefix="ok_test_",
    )
    db_session.commit()
    db_session.refresh(api_key)
    api_key.plaintext = plaintext_key
    return api_key


@pytest.fixture
def expired_api_key(db_session, test_user, test_organization):
    expired_date = (utcnow() - timedelta(days=1)).replace(tzinfo=None)
    api_key, plaintext_key = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_user.id,
        organization_id=test_organization.id,
        name="Expired Key",
        prefix="ok_test_",
        expires_at=expired_date,
    )
    db_session.commit()
    db_session.refresh(api_key)
    api_key.plaintext = plaintext_key
    return api_key


@pytest.fixture
def admin_api_key(db_session, test_admin_user, test_organization):
    api_key, plaintext_key = APIKeyService.create_api_key(
        db=db_session,
        user_id=test_admin_user.id,
        organization_id=test_organization.id,
        name="Admin Key",
        prefix="ok_test_",
    )
    db_session.commit()
    db_session.refresh(api_key)
    api_key.plaintext = plaintext_key
    return api_key


class _AuthClient:
    """Wrapper that delegates to a TestClient with auth headers on every request."""

    def __init__(self, inner, token):
        self._inner = inner
        self._headers = {"Authorization": f"Bearer {token}"}

    def _merge(self, kwargs):
        h = dict(self._headers)
        h.update(kwargs.get("headers", {}))
        kwargs["headers"] = h
        return kwargs

    @property
    def app(self):
        return self._inner.app

    def get(self, *a, **kw):
        return self._inner.get(*a, **self._merge(kw))

    def post(self, *a, **kw):
        return self._inner.post(*a, **self._merge(kw))

    def put(self, *a, **kw):
        return self._inner.put(*a, **self._merge(kw))

    def patch(self, *a, **kw):
        return self._inner.patch(*a, **self._merge(kw))

    def delete(self, *a, **kw):
        return self._inner.delete(*a, **self._merge(kw))

    @property
    def headers(self):
        return self._headers

    @headers.setter
    def headers(self, value):
        self._headers = dict(value)


@pytest.fixture
def authenticated_client(client, test_api_key):
    """Test client authenticated as a regular user."""
    return _AuthClient(client, test_api_key.plaintext)


@pytest.fixture
def admin_client(client, admin_api_key):
    """Test client authenticated as an admin user."""
    return _AuthClient(client, admin_api_key.plaintext)


@pytest.fixture
def mock_auth(db_session, app, monkeypatch):
    """Mock authentication for arbitrary users."""
    import app.shared.core.auth_middleware as auth_mw

    _original_call = auth_mw.ASGIAuthMiddleware.__call__
    _mock_user = None
    _mock_org = None

    async def _patched_call(self, scope, receive, send):
        """Skip DB session creation entirely when mock is active."""
        if _mock_user is not None and scope["type"] in ("http", "websocket"):
            path = scope.get("path", "/")
            method = scope.get("method", "GET")
            if method == "OPTIONS" or auth_mw._is_public(path, method):
                await self.app(scope, receive, send)
                return
            # Inject mock user directly — no DB session needed
            scope.setdefault("state", {})
            scope["state"]["user"] = _mock_user
            scope["state"]["organization"] = _mock_org
            scope["state"]["api_key"] = None
            await self.app(scope, receive, send)
            return
        await _original_call(self, scope, receive, send)

    monkeypatch.setattr(auth_mw.ASGIAuthMiddleware, "__call__", _patched_call)

    def _set_mock(user):
        nonlocal _mock_user, _mock_org
        if user.organization_id and "organization" not in user.__dict__:
            user.organization = db_session.get(Organization, user.organization_id)
        _mock_user = user
        _mock_org = user.organization

    yield _set_mock


@pytest.fixture
def enable_registration(db_session):
    from app.services.platform_settings_service import PlatformSettingsService

    PlatformSettingsService.set(db_session, "REGISTRATION_ENABLED", "true")
    db_session.commit()
