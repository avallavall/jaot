"""Lightweight circuit breaker for RAG external services (Qdrant, Voyage).

Prevents cascading failures when Qdrant or Voyage is down. After
``FAILURE_THRESHOLD`` consecutive failures, the circuit opens for
``RECOVERY_TIMEOUT`` seconds. During this time, ``is_open`` returns True
and callers should skip the RAG path entirely (graceful degradation).
"""

from __future__ import annotations

import time

from app.services.rag.config import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
)


class RAGCircuitBreaker:
    """In-process circuit breaker for RAG services.

    States:
        closed    — normal operation, requests flow through
        open      — failures exceeded threshold, requests are blocked
        half_open — recovery timeout elapsed, allow one probe request
    """

    def __init__(
        self,
        failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "closed"

    @property
    def is_open(self) -> bool:
        """Return True if the circuit is open (should skip RAG)."""
        if self._state == "open":
            if time.monotonic() - self._last_failure_time > self._recovery_timeout:
                self._state = "half_open"
                return False
            return True
        return False

    @property
    def state(self) -> str:
        """Return the current circuit state."""
        # Trigger timeout check via is_open
        _ = self.is_open
        return self._state

    def record_success(self) -> None:
        """Record a successful RAG operation. Resets the circuit."""
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed RAG operation. May open the circuit."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = "open"
