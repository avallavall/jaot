"""LLM error taxonomy — public (user-actionable) vs internal (opaque to user).

The goal is to never leak internal implementation detail (Anthropic API errors,
stack traces, token counts, retry state) into SSE events that reach the chat
UI. Instead:

1. Backend code raises a typed exception or yields an event with a stable
   :class:`LLMErrorCode`. Human-readable detail goes to structured logs
   (``logger.error(..., extra={"event_code": ...})``) and Prometheus counters.
2. The client receives ``{"code": "...", "severity": "...", "request_id": "..."}``
   and translates the code via next-intl. Unknown codes fall back to
   ``INTERNAL_ERROR``.

Classification rules:

* Public codes carry information the user can act on (reformulate, top up
  credits, fix validation). The frontend may show the concrete message.
* Internal codes surface as a generic "service unavailable" / "internal error"
  to the user. Detail stays server-side. This covers Anthropic upstream
  failures (rate limit, overload, quota exhaustion, auth) and unexpected
  exceptions.

Example::

    try:
        async for chunk in client.messages.stream(...):
            ...
    except anthropic.APIStatusError as exc:
        code, metric_kind = classify_anthropic_error(exc)
        logger.error(
            "Anthropic API error",
            exc_info=True,
            extra={"event_code": f"llm.upstream_{metric_kind}"},
        )
        LLM_UPSTREAM_ERRORS.labels(provider="anthropic", kind=metric_kind).inc()
        raise InternalLLMError(code) from exc
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, TypedDict


class LLMErrorCode(str, Enum):
    """Stable client-facing error codes.

    Members are grouped into *public* (safe to show to end users with
    the detailed message) and *internal* (shown as generic "service
    unavailable"). The raw value is the wire format — never rename a
    member without a deprecation window.
    """

    # --- Public (user-actionable) ---
    VALIDATION_FAILED = "validation_failed"
    CONTENT_MODERATION = "content_moderation"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    PARAMETRIC_UNSUPPORTED = "parametric_unsupported"

    # --- Internal (generic message to user, detail in logs) ---
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"


PUBLIC_CODES: frozenset[LLMErrorCode] = frozenset(
    {
        LLMErrorCode.VALIDATION_FAILED,
        LLMErrorCode.CONTENT_MODERATION,
        LLMErrorCode.INSUFFICIENT_CREDITS,
        LLMErrorCode.PARAMETRIC_UNSUPPORTED,
    }
)


def is_public(code: LLMErrorCode) -> bool:
    """Return True when the code is safe to surface verbatim to users."""
    return code in PUBLIC_CODES


class LLMStatusCode(str, Enum):
    """Stable client-facing status event codes (streaming progress only).

    These replace the free-form ``chunk_progress`` / ``status`` messages
    that previously leaked internals like retry counts, token budgets,
    and phase names to the chat UI. The frontend maps each code to an
    i18n key under ``builder.llm.status.*``.
    """

    GENERATING = "generating"
    GENERATING_VARIABLES = "generating_variables"
    GENERATING_CONSTRAINTS = "generating_constraints"
    ASSEMBLING = "assembling"


class LLMServiceError(Exception):
    """Base class for LLM errors with a stable client-facing code."""

    def __init__(self, code: LLMErrorCode, *, detail: str | None = None) -> None:
        super().__init__(detail or code.value)
        self.code = code
        # ``detail`` is never serialized to clients for internal codes; it
        # exists so callers can log a human-readable reason alongside the
        # structured ``event_code`` extra.
        self.detail = detail


class PublicLLMError(LLMServiceError):
    """LLM error whose detail is safe to show to the end user.

    Raised only for user-actionable conditions (validation, moderation,
    insufficient credits, unsupported formulation). The ``detail`` field
    MAY be included in the SSE payload.
    """

    def __init__(self, code: LLMErrorCode, *, detail: str | None = None) -> None:
        if not is_public(code):
            raise ValueError(f"{code} is not a public code; use InternalLLMError instead")
        super().__init__(code, detail=detail)


class InternalLLMError(LLMServiceError):
    """LLM error whose detail must NOT reach the client.

    The user receives a generic message derived from ``code`` (e.g.
    ``service_unavailable``). The ``detail`` stays server-side in logs
    and metrics. Wrap upstream exceptions with ``raise InternalLLMError(...)
    from exc`` to preserve the traceback for log inspection.
    """

    def __init__(self, code: LLMErrorCode, *, detail: str | None = None) -> None:
        if is_public(code):
            raise ValueError(f"{code} is a public code; use PublicLLMError instead")
        super().__init__(code, detail=detail)


def _extract_error_body_message(exc: Exception) -> str:
    """Pull the lower-cased message out of an Anthropic error body.

    The SDK exposes ``exc.body`` (parsed JSON) on ``APIStatusError`` with
    shape ``{"type": "error", "error": {"type": "...", "message": "..."}}``.
    Reading the structured field is more robust than ``str(exc)`` which
    depends on the SDK's ``__str__`` formatting.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error_obj = body.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message", "")
            if isinstance(message, str):
                return message.lower()
    return ""


def classify_anthropic_error(exc: Exception) -> tuple[LLMErrorCode, str]:
    """Map an Anthropic SDK exception to (client code, metric kind).

    ``metric kind`` is the value for the ``kind`` label on
    ``jaot_llm_upstream_errors_total`` and is intentionally more
    granular than the client-facing code — quota exhaustion and a plain
    rate-limit response both map to ``SERVICE_UNAVAILABLE`` for the user
    but are tracked separately in Grafana so the admin alert for
    exhausted billing fires only on the right condition.

    Returns:
        Tuple of ``(LLMErrorCode, metric_kind)``. The metric kind is one
        of: ``quota_exhausted``, ``rate_limit``, ``auth_failed``,
        ``overloaded``, ``timeout``, ``connection``, ``api_error``,
        ``unexpected``, ``unknown``.
    """
    # Import lazily so this module stays importable in environments
    # where the anthropic SDK is not installed (tests, tooling).
    try:
        import anthropic
    except ImportError:  # pragma: no cover — anthropic is a hard dep in prod
        return LLMErrorCode.SERVICE_UNAVAILABLE, "unknown"

    # Credit/quota exhaustion surfaces as a 400 BadRequestError body with
    # ``credit_balance_too_low`` in the message. Prefer the structured
    # body over the repr so an SDK wording change does not silently break
    # the Alertmanager quota rule. Fall back to ``str(exc)`` so ad-hoc
    # ``Exception("... credit_balance_too_low ...")`` in tests still work.
    body_message = _extract_error_body_message(exc)
    fallback_str = str(exc).lower()
    if (
        "credit_balance_too_low" in body_message
        or "insufficient_quota" in body_message
        or "credit_balance_too_low" in fallback_str
        or "insufficient_quota" in fallback_str
    ):
        return LLMErrorCode.SERVICE_UNAVAILABLE, "quota_exhausted"

    # APITimeoutError is a subclass of APIConnectionError in the SDK, so
    # it must be checked first or it gets mislabeled as ``connection``.
    timeout_cls = getattr(anthropic, "APITimeoutError", None)
    if timeout_cls is not None and isinstance(exc, timeout_cls):
        return LLMErrorCode.SERVICE_UNAVAILABLE, "timeout"

    if isinstance(exc, anthropic.RateLimitError):
        return LLMErrorCode.SERVICE_UNAVAILABLE, "rate_limit"

    if isinstance(exc, anthropic.AuthenticationError):
        return LLMErrorCode.SERVICE_UNAVAILABLE, "auth_failed"

    if isinstance(exc, anthropic.APIConnectionError):
        return LLMErrorCode.SERVICE_UNAVAILABLE, "connection"

    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        if status == 529:
            return LLMErrorCode.SERVICE_UNAVAILABLE, "overloaded"
        if status == 408:
            return LLMErrorCode.SERVICE_UNAVAILABLE, "timeout"
        return LLMErrorCode.SERVICE_UNAVAILABLE, "api_error"

    # Any other exception — not an Anthropic error at all.
    return LLMErrorCode.INTERNAL_ERROR, "unexpected"


class LLMErrorEvent(TypedDict):
    """Shape of the SSE error event dict returned by handle_anthropic_failure."""

    type: str  # always "error"
    code: LLMErrorCode


def handle_anthropic_failure(
    exc: Exception,
    *,
    logger: logging.Logger,
    context: str,
    request_id: str | None = None,
) -> LLMErrorEvent:
    """Classify an exception, log it with structured context, bump the
    upstream-error counter, and return the SSE error event dict ready to
    yield from a streaming generator.

    Centralizes the classify → log → metric → yield pattern so a change
    to logging fields, metric labels, or the SSE shape happens in one
    place. Callers look like::

        yield handle_anthropic_failure(exc, logger=logger, context="text response")
    """
    # Local import so errors.py stays free of hard dependencies on the
    # metrics module at import time (avoids circular imports during tests
    # that patch the metric registry).
    from app.shared.core.prometheus_metrics import LLM_UPSTREAM_ERRORS

    code, metric_kind = classify_anthropic_error(exc)
    extra: dict[str, Any] = {"event_code": f"llm.upstream_{metric_kind}"}
    if request_id:
        extra["request_id"] = request_id
    logger.error(
        "LLM upstream failure (%s, kind=%s)",
        context,
        metric_kind,
        exc_info=True,
        extra=extra,
    )
    LLM_UPSTREAM_ERRORS.labels(provider="anthropic", kind=metric_kind).inc()
    return {"type": "error", "code": code}
