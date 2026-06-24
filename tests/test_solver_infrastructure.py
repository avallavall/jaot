"""Tests for solver infrastructure: thread pool, timeout, Redis backend, error codes."""

from unittest.mock import MagicMock


class TestCeleryConfiguration:
    """Test Celery app configuration."""

    def test_result_expires_7_days(self):
        """Result expiry should be 7 days (604800 seconds)."""
        from app.shared.core.celery_app import celery_app

        assert celery_app.conf.result_expires == 604800

    def test_celery_includes_solve_tasks(self):
        """Celery app should include solve tasks."""
        from app.shared.core.celery_app import celery_app

        assert "app.domains.solver.tasks.solve_tasks" in celery_app.conf.include


class TestSolverPoolConfig:
    """Test solver thread pool configuration (via platform_settings DB)."""

    def test_default_pool_size(self, db_session):
        """Default solver pool size should be 4."""
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        assert PSS.get_int(db_session, "SOLVER_POOL_SIZE") == 4

    def test_default_timeout(self, db_session):
        """Default solver timeout should be 30 seconds."""
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        assert PSS.get_int(db_session, "SOLVER_TIMEOUT_SECONDS") == 30

    def test_pool_size_is_positive(self, db_session):
        """Pool size must be a positive integer."""
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        assert PSS.get_int(db_session, "SOLVER_POOL_SIZE") > 0

    def test_timeout_is_positive(self, db_session):
        """Timeout must be a positive integer."""
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        assert PSS.get_int(db_session, "SOLVER_TIMEOUT_SECONDS") > 0


class TestErrorCodes:
    """Test structured error codes exist."""

    def test_solve_timeout_error_code(self):
        from app.shared.core.exceptions import SOLVE_TIMEOUT

        assert SOLVE_TIMEOUT == "SOLVE_TIMEOUT"

    def test_pool_exhausted_error_code(self):
        from app.shared.core.exceptions import POOL_EXHAUSTED

        assert POOL_EXHAUSTED == "POOL_EXHAUSTED"

    def test_expr_parse_error_code(self):
        from app.shared.core.exceptions import EXPR_PARSE_ERROR

        assert EXPR_PARSE_ERROR == "EXPR_PARSE_ERROR"

    def test_solve_timeout_exception(self):
        from app.shared.core.exceptions import SolveTimeoutError

        err = SolveTimeoutError(30.0)
        assert "30" in str(err)
        assert err.details["error_code"] == "SOLVE_TIMEOUT"
        assert err.details["timeout_seconds"] == 30.0

    def test_pool_exhausted_exception(self):
        from app.shared.core.exceptions import PoolExhaustedError

        err = PoolExhaustedError()
        assert "/api/v2/solve/async" in err.details.get("suggested_endpoint", "")
        assert err.details["error_code"] == "POOL_EXHAUSTED"

    def test_solve_timeout_suggests_async(self):
        """SolveTimeoutError message should suggest the async endpoint."""
        from app.shared.core.exceptions import SolveTimeoutError

        err = SolveTimeoutError(30.0)
        assert "async" in str(err).lower()

    def test_pool_exhausted_suggests_async(self):
        """PoolExhaustedError message should suggest the async endpoint."""
        from app.shared.core.exceptions import PoolExhaustedError

        err = PoolExhaustedError()
        assert "async" in str(err).lower()


class TestVerboseMode:
    """Test verbose error mode via X-Jaot-Debug header."""

    def test_verbose_header_detection(self):
        """X-Jaot-Debug: true activates verbose mode for admin users (M-4 fix)."""
        from app.api.v2.solve import _is_verbose

        mock_request = MagicMock()
        mock_request.headers = {"X-Jaot-Debug": "true"}
        mock_request.state.user = MagicMock(is_admin=True)
        assert _is_verbose(mock_request) is True

    def test_non_verbose_by_default(self):
        """Without header, verbose mode is off."""
        from app.api.v2.solve import _is_verbose

        mock_request = MagicMock()
        mock_request.headers = {}
        assert _is_verbose(mock_request) is False

    def test_verbose_header_case_insensitive(self):
        """X-Jaot-Debug: TRUE also activates verbose mode for admin users (M-4 fix)."""
        from app.api.v2.solve import _is_verbose

        mock_request = MagicMock()
        mock_request.headers = {"X-Jaot-Debug": "TRUE"}
        mock_request.state.user = MagicMock(is_admin=True)
        assert _is_verbose(mock_request) is True

    def test_verbose_denied_for_non_admin(self):
        """X-Jaot-Debug: true is ignored for non-admin users (M-4 fix)."""
        from app.api.v2.solve import _is_verbose

        mock_request = MagicMock()
        mock_request.headers = {"X-Jaot-Debug": "true"}
        mock_request.state.user = MagicMock(is_admin=False)
        assert _is_verbose(mock_request) is False

    def test_error_response_verbose(self):
        """Verbose error response includes details (admin only)."""
        from app.api.v2.solve import _error_response

        mock_request = MagicMock()
        mock_request.headers = {"X-Jaot-Debug": "true"}
        mock_request.state.user = MagicMock(is_admin=True)
        resp = _error_response("SOLVE_TIMEOUT", "Timed out", mock_request, timeout=30)
        assert "details" in resp
        assert resp["details"]["timeout"] == 30

    def test_error_response_non_verbose(self):
        """Non-verbose error response omits details."""
        from app.api.v2.solve import _error_response

        mock_request = MagicMock()
        mock_request.headers = {}
        resp = _error_response("SOLVE_TIMEOUT", "Timed out", mock_request, timeout=30)
        assert "details" not in resp

    def test_error_response_includes_error_and_message(self):
        """Error response always includes error code and message."""
        from app.api.v2.solve import _error_response

        mock_request = MagicMock()
        mock_request.headers = {}
        resp = _error_response("POOL_EXHAUSTED", "At capacity", mock_request)
        assert resp["error"] == "POOL_EXHAUSTED"
        assert resp["message"] == "At capacity"


class TestThreadPoolExecutor:
    """Test that solver thread pool executor is created lazily."""

    def test_solver_pool_exists(self):
        """get_solver_pool() should return a pool."""
        from app.domains.solver.services.pool import get_solver_pool

        pool = get_solver_pool()
        assert pool is not None

    def test_solver_pool_max_workers(self, db_session):
        """Pool max_workers should match config."""
        from app.domains.solver.services.pool import get_solver_pool
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        pool = get_solver_pool()
        expected = PSS.get_int(db_session, "SOLVER_POOL_SIZE")
        assert pool._max_workers == expected

    def test_solver_pool_thread_prefix(self):
        """Pool threads should have 'solver' prefix."""
        from app.domains.solver.services.pool import get_solver_pool

        pool = get_solver_pool()
        assert pool._thread_name_prefix == "solver"
