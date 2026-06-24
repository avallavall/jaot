"""Custom exceptions for JAOT."""

from typing import Any


class JaotError(Exception):
    """Base exception for all JAOT errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class PluginNotFoundError(JaotError):
    """Raised when a requested plugin is not found."""

    def __init__(self, plugin_name: str):
        super().__init__(
            message=f"Plugin '{plugin_name}' not found", details={"plugin_name": plugin_name}
        )


class PluginValidationError(JaotError):
    """Raised when plugin data validation fails."""

    def __init__(self, errors: list[str]):
        super().__init__(message="Plugin validation failed", details={"errors": errors})


class SolverError(JaotError):
    """Raised when solver execution fails."""

    def __init__(self, message: str, solver_status: str | None = None):
        super().__init__(
            message=message, details={"solver_status": solver_status} if solver_status else {}
        )


SOLVE_TIMEOUT = "SOLVE_TIMEOUT"
POOL_EXHAUSTED = "POOL_EXHAUSTED"
EXPR_PARSE_ERROR = "EXPR_PARSE_ERROR"


class SolveTimeoutError(JaotError):
    """Raised when a synchronous solve exceeds the timeout."""

    def __init__(self, timeout_seconds: float):
        super().__init__(
            message=(
                f"Solve timed out after {timeout_seconds}s. "
                "Consider using the async endpoint for complex problems."
            ),
            details={"error_code": SOLVE_TIMEOUT, "timeout_seconds": timeout_seconds},
        )


class PoolExhaustedError(JaotError):
    """Raised when the thread pool has no available workers."""

    def __init__(self) -> None:
        super().__init__(
            message=(
                "Server is at capacity. "
                "Please use the async solve endpoint: POST /api/v2/solve/async"
            ),
            details={
                "error_code": POOL_EXHAUSTED,
                "suggested_endpoint": "/api/v2/solve/async",
            },
        )
