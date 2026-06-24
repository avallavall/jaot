"""Prometheus metric definitions for JAOT business metrics.

All metric names are prefixed with `jaot_` for namespace clarity.
These are global metrics only -- no per-organization labels to avoid cardinality explosion.
"""

from enum import StrEnum

from prometheus_client import Counter, Gauge, Histogram, Info


class RefundReason(StrEnum):
    """Bounded-cardinality label values for credit-refund audit/metric calls.

    Q-29 — collapses free-form ``description=`` strings that the refund
    path emitted into a closed enum. Prometheus counter
    ``CREDITS_REFUNDED`` labels by this enum; audit / log messages also
    key off the same value so ops has a single vocabulary for
    "why did this refund fire".

    Add a new value here (not a new string) whenever a new refund path
    lands — keeps dashboards / alerts in sync by grep.
    """

    # Solver returned status=error without raising (D-19 success-with-error
    # branch — EXPR_PARSE_ERROR etc.).
    SOLVER_LEVEL_ERROR = "solver_level_error"
    # Celery task raised (except-branch refund).
    TASK_EXCEPTION = "task_exception"
    # SolveOrchestrator sync-path refund (timeout or solver-level error).
    ORCHESTRATOR_FAILURE = "orchestrator_failure"
    # solve_model_async failure-path refund when the producer pre-paid.
    MODEL_EXECUTION_FAILED = "model_execution_failed"
    # apply_async / routing failure AFTER a pre-pay committed (solve.py
    # async-enqueue path, execution.py model-async path).
    ENQUEUE_FAILED = "enqueue_failed"
    # Post-pre-pay rejection because the requested solver name did not
    # resolve to a queue (unknown solver at dispatch time).
    UNKNOWN_SOLVER = "unknown_solver"
    # Periodic execution reaper (W1/F-01) refunded a stale pending/running
    # execution whose task never resolved (lost, hung, or hard-killed).
    EXECUTION_REAPED = "execution_reaped"


SOLVE_TOTAL = Counter(
    "jaot_solve_total",
    "Total optimization solve requests",
    labelnames=["status", "generator"],
)

CREDITS_CONSUMED = Counter(
    "jaot_credits_consumed_total",
    "Total credits consumed across all organizations",
)

# E-19 — pre-paid solve credits refunded on task failure. Bounded label by
# RefundReason (closed enum). Total credit movement on the refund side is
# visible in Grafana even when CREDITS_CONSUMED is flat (ops can distinguish
# "nothing ran" from "lots ran but all refunded due to solver crash").
CREDITS_REFUNDED = Counter(
    "jaot_credits_refunded_total",
    "Pre-paid solve credits refunded on task failure.",
    labelnames=["reason"],  # RefundReason enum — closed vocabulary
)

SOLVE_DURATION = Histogram(
    "jaot_solve_duration_seconds",
    "Duration of solver execution in seconds",
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120],
)

ACTIVE_SOLVES = Gauge(
    "jaot_active_solves",
    "Number of currently running solver instances",
)

# Auto-routing observability (Phase 7.4 / D-13 / INT-01)
#
# SOLVER_AUTO_ROUTE_DECISIONS bounds cardinality with 2 closed-vocabulary
# labels: solver_used ∈ {scip, highs, hexaly} and reason ∈ {lp_routed_to_highs,
# quadratic_routed_to_hexaly, milp_routed_to_scip, hexaly_unavailable_fallback}.

SOLVER_AUTO_ROUTE_DECISIONS = Counter(
    "jaot_solver_auto_route_decisions_total",
    "Auto-routing decisions by effective solver and reason slug",
    labelnames=["solver_used", "reason"],
)

# Hexaly platform license expiry (Phase 7.4 / D-07 / HEX-09)
#
# Cardinality is bounded by a single label (license_fingerprint = sha256[:8]
# of the .lic plaintext). Plan 06 wires the daily Celery beat sweep that
# updates this gauge.

HEXALY_LICENSE_DAYS_REMAINING = Gauge(
    "jaot_hexaly_platform_license_days_remaining",
    "Days until the platform Hexaly license expires (-1 if unknown/unparseable)",
    labelnames=["license_fingerprint"],
)

# LLM metrics
#
# Track upstream LLM failures separately from generic HTTP metrics so the
# admin can see "Anthropic is out of quota" at a glance in Grafana and
# Alertmanager can page on quota exhaustion without noise from unrelated
# 5xx traffic. Labels are bounded (provider ∈ {anthropic}, kind ∈ a fixed
# enum from classify_anthropic_error) to keep cardinality tiny.

LLM_REQUESTS_TOTAL = Counter(
    "jaot_llm_requests_total",
    "Total LLM formulation requests",
    labelnames=["outcome"],  # success | error
)

LLM_UPSTREAM_ERRORS = Counter(
    "jaot_llm_upstream_errors_total",
    "LLM upstream provider errors categorized by kind",
    # kind ∈ rate_limit | overloaded | quota_exhausted | auth_failed
    #      | connection | timeout | api_error | unexpected
    labelnames=["provider", "kind"],
)

LLM_RETRIES_TOTAL = Counter(
    "jaot_llm_retries_total",
    "LLM auto-retries triggered by truncation or transient failures",
    labelnames=["reason"],  # truncation | chunked_fallback
)

# Contact form (Phase 9 / D-01 / D-04 / T-09-09)
#
# Bounded-cardinality labels:
#   CONTACT_SPAM_BLOCKED.reason ∈ {honeypot, rate_limit_minute, rate_limit_day, validation}
#   CONTACT_SEND_ATTEMPTS.result ∈ {sent, retry, failed}
# NO user-supplied values appear as labels — T-09-09 PII-redaction.

CONTACT_SPAM_BLOCKED = Counter(
    "jaot_contact_spam_blocked_total",
    "Contact-form submissions blocked by anti-spam guards (honeypot, rate-limit, validation).",
    labelnames=["reason"],
)

CONTACT_SEND_ATTEMPTS = Counter(
    "jaot_contact_message_send_attempts_total",
    "Attempts to deliver a contact_messages row via SMTP (Celery task).",
    labelnames=["result"],
)


APP_INFO = Info(
    "jaot_app",
    "JAOT application information",
)


def init_app_info(version: str = "2.0.0") -> None:
    """Initialize application info metric. Called once at startup."""
    APP_INFO.info({"version": version, "solver": "scip"})
