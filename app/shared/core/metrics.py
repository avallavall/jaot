"""In-memory metrics system for tracking application performance."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

from app.shared.utils.datetime_helpers import utcnow


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    problem_type: str
    timestamp: datetime
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class ProblemStats:
    """Aggregated statistics for a problem type."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    last_request: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration."""
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_ms / self.total_requests


class MetricsCollector:
    """Thread-safe in-memory metrics collector."""

    def __init__(self, max_recent_requests: int = 100):
        """Initialize metrics collector.

        Args:
            max_recent_requests: Maximum number of recent requests to keep in memory
        """
        self.max_recent_requests = max_recent_requests
        self._lock = Lock()

        # Global stats
        self._start_time = utcnow()
        self._problem_stats: dict[str, ProblemStats] = defaultdict(ProblemStats)

        # Recent requests (circular buffer)
        self._recent_requests: list[RequestMetrics] = []

    def record_request(
        self, problem_type: str, duration_ms: float, success: bool, error: str | None = None
    ) -> None:
        """Record a request's metrics.

        Args:
            problem_type: Type of problem solved
            duration_ms: Duration in milliseconds
            success: Whether the request was successful
            error: Error message if failed
        """
        with self._lock:
            timestamp = utcnow()

            stats = self._problem_stats[problem_type]
            stats.total_requests += 1
            stats.total_duration_ms += duration_ms
            stats.last_request = timestamp

            if success:
                stats.successful_requests += 1
            else:
                stats.failed_requests += 1

            if duration_ms < stats.min_duration_ms:
                stats.min_duration_ms = duration_ms
            if duration_ms > stats.max_duration_ms:
                stats.max_duration_ms = duration_ms

            # Add to recent requests (circular buffer)
            request_metric = RequestMetrics(
                problem_type=problem_type,
                timestamp=timestamp,
                duration_ms=duration_ms,
                success=success,
                error=error,
            )

            self._recent_requests.append(request_metric)
            if len(self._recent_requests) > self.max_recent_requests:
                self._recent_requests.pop(0)

    def get_stats(self, problem_type: str | None = None) -> dict[str, Any]:
        """Get statistics for a problem type or all problems.

        Args:
            problem_type: Specific problem type, or None for all

        Returns:
            Dictionary with statistics
        """
        with self._lock:
            if problem_type:
                if problem_type not in self._problem_stats:
                    return {}

                stats = self._problem_stats[problem_type]
                min_duration = (
                    round(stats.min_duration_ms, 2)
                    if stats.min_duration_ms != float("inf")
                    else None
                )
                last_request = stats.last_request.isoformat() if stats.last_request else None
                return {
                    "problem_type": problem_type,
                    "total_requests": stats.total_requests,
                    "successful_requests": stats.successful_requests,
                    "failed_requests": stats.failed_requests,
                    "success_rate": round(stats.success_rate, 2),
                    "avg_duration_ms": round(stats.avg_duration_ms, 2),
                    "min_duration_ms": min_duration,
                    "max_duration_ms": round(stats.max_duration_ms, 2),
                    "last_request": last_request,
                }

            uptime = (utcnow() - self._start_time).total_seconds()
            total_requests = sum(s.total_requests for s in self._problem_stats.values())
            total_successful = sum(s.successful_requests for s in self._problem_stats.values())
            total_failed = sum(s.failed_requests for s in self._problem_stats.values())

            problem_stats: dict[str, dict[str, float | int | None | str]] = {}
            for problem_name, stats in self._problem_stats.items():
                min_duration = (
                    round(stats.min_duration_ms, 2)
                    if stats.min_duration_ms != float("inf")
                    else None
                )
                last_request = stats.last_request.isoformat() if stats.last_request else None
                problem_stats[problem_name] = {
                    "total_requests": stats.total_requests,
                    "successful_requests": stats.successful_requests,
                    "failed_requests": stats.failed_requests,
                    "success_rate": round(stats.success_rate, 2),
                    "avg_duration_ms": round(stats.avg_duration_ms, 2),
                    "min_duration_ms": min_duration,
                    "max_duration_ms": round(stats.max_duration_ms, 2),
                    "last_request": last_request,
                }

            return {
                "uptime_seconds": uptime,
                "start_time": self._start_time.isoformat(),
                "total_requests": total_requests,
                "total_successful": total_successful,
                "total_failed": total_failed,
                "problem_stats": problem_stats,
            }

    def get_recent_requests(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Get recent requests.

        Args:
            limit: Maximum number of requests to return

        Returns:
            List of recent request metrics
        """
        with self._lock:
            requests = self._recent_requests[-limit:] if limit else self._recent_requests
            return [
                {
                    "problem_type": req.problem_type,
                    "timestamp": req.timestamp.isoformat(),
                    "duration_ms": round(req.duration_ms, 2),
                    "success": req.success,
                    "error": req.error,
                }
                for req in requests
            ]

    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        with self._lock:
            self._start_time = utcnow()
            self._problem_stats.clear()
            self._recent_requests.clear()


# Global metrics collector instance
metrics_collector = MetricsCollector()
