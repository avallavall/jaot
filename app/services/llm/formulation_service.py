"""Formulation generation service using Anthropic Claude.

Streams structured formulation output from Claude, validates the result,
and yields events for SSE consumption. Includes truncation detection and
auto-retry with escalating max_tokens.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.schemas.llm import FORMULATION_JSON_SCHEMA, Formulation
from app.services.llm.anthropic_client import get_anthropic_client
from app.services.llm.errors import (
    LLMErrorCode,
    LLMStatusCode,
    handle_anthropic_failure,
)
from app.services.llm.prompt_templates import FORMULATION_SYSTEM_PROMPT
from app.services.llm.token_estimation import (
    estimate_output_tokens,
    is_json_incomplete,
)
from app.services.llm.validation import validate_formulation
from app.shared.core.prometheus_metrics import LLM_RETRIES_TOTAL

logger = logging.getLogger(__name__)


def _pss_str(db: Any | None, key: str) -> str:
    """Read a string setting from DB, opening a session if needed."""
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )

    if db is not None:
        return PSS.get_str(db, key)
    from app.shared.db.session import SessionLocal

    _db = SessionLocal()
    try:
        return PSS.get_str(_db, key)
    finally:
        _db.close()


def _pss_int(db: Any | None, key: str) -> int:
    """Read an int setting from DB, opening a session if needed."""
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )

    if db is not None:
        return PSS.get_int(db, key)
    from app.shared.db.session import SessionLocal

    _db = SessionLocal()
    try:
        return PSS.get_int(_db, key)
    finally:
        _db.close()


def select_model(use_advanced: bool, db: Any | None = None) -> tuple[str, bool]:
    """Select the LLM model and whether to use extended thinking.

    Args:
        use_advanced: If True, use the advanced model with thinking.
        db: Optional DB session for runtime settings.

    Returns:
        Tuple of (model_name, use_thinking).
    """
    if use_advanced:
        return _pss_str(db, "LLM_ADVANCED_MODEL"), True
    return _pss_str(db, "LLM_DEFAULT_MODEL"), False


async def generate_formulation(
    messages: list[dict[str, Any]],
    model: str,
    thinking: bool = False,
    max_tokens: int | None = None,
    system_prompt: str | None = None,
    db: Any | None = None,
    client: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Generate a structured formulation from conversation messages.

    Streams the response from Claude and yields events:
    - {"type": "delta", "text": "..."} for each text chunk
    - {"type": "formulation", "data": {...}} when complete formulation is parsed
    - {"type": "validation_errors", "data": [...]} if validation issues found
    - {"type": "truncation_warning"} (internal, consumed by resilient wrapper)
    - {"type": "done"} when finished
    - {"type": "error", "code": LLMErrorCode} on failure — the ``code`` is a
      stable enum value the frontend maps to an i18n key; no raw exception
      detail is ever included.

    Args:
        messages: Anthropic API messages list (from build_messages).
        model: Model ID to use (e.g. "claude-sonnet-4-6").
        thinking: Whether to enable extended thinking (for Opus).
        max_tokens: Override max output tokens (default: LLM_MAX_TOKENS).
        db: Optional DB session for runtime settings.

    Yields:
        Event dicts for SSE streaming.
    """
    # BYOK: when the caller resolved an org-specific client, use it; otherwise
    # create the shared platform client via the (test-patchable) factory.
    client = client or get_anthropic_client(db=db)

    default_max = _pss_int(db, "LLM_MAX_TOKENS")
    effective_max_tokens = max_tokens or default_max

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": effective_max_tokens,
        "system": system_prompt or FORMULATION_SYSTEM_PROMPT,
        "messages": messages,
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": FORMULATION_JSON_SCHEMA,
            }
        },
    }

    # Extended thinking for advanced model
    if thinking:
        thinking_budget = _pss_int(db, "LLM_THINKING_BUDGET_TOKENS")
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_budget,
        }

    accumulated_text = ""
    stop_reason = None
    usage_input_tokens = 0
    usage_output_tokens = 0

    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # W17: real token usage. message_start carries input_tokens;
                # message_delta carries the cumulative output_tokens.
                if event.type == "message_start":
                    _usage = getattr(getattr(event, "message", None), "usage", None)
                    _in = getattr(_usage, "input_tokens", None)
                    if isinstance(_in, int):
                        usage_input_tokens = _in
                    continue

                # Track stop_reason + usage from message_delta
                if event.type == "message_delta":
                    if hasattr(event.delta, "stop_reason"):
                        stop_reason = event.delta.stop_reason
                    _out = getattr(getattr(event, "usage", None), "output_tokens", None)
                    if isinstance(_out, int):
                        usage_output_tokens = _out
                    continue

                # Handle content block deltas
                if event.type == "content_block_delta":
                    # Skip thinking deltas (hidden per user decision)
                    if hasattr(event.delta, "type") and event.delta.type == "thinking_delta":
                        continue

                    # Text delta
                    if hasattr(event.delta, "text"):
                        chunk = event.delta.text
                        accumulated_text += chunk
                        yield {"type": "delta", "text": chunk}

        # Belt-and-suspenders truncation detection
        truncated = stop_reason == "max_tokens" or is_json_incomplete(accumulated_text)

        if truncated:
            logger.warning(
                "Response truncated (stop_reason=%s, json_incomplete=%s, max_tokens=%d)",
                stop_reason,
                is_json_incomplete(accumulated_text),
                effective_max_tokens,
                extra={"event_code": "llm.truncation"},
            )
            # Internal marker consumed by generate_formulation_resilient.
            # Never yielded to the client directly.
            yield {
                "type": "truncation_warning",
                "accumulated_text": accumulated_text,
            }
        else:
            # Stream completed normally -- parse the accumulated JSON
            try:
                formulation_dict = json.loads(accumulated_text)
                formulation = Formulation.model_validate(formulation_dict)
                formulation_data = formulation.model_dump()

                yield {"type": "formulation", "data": formulation_data}

                # Run validation
                errors = validate_formulation(formulation_data)
                if errors:
                    yield {"type": "validation_errors", "data": errors}

            except json.JSONDecodeError as e:
                # JSON parse failure despite is_json_incomplete returning False.
                # Treat as truncation so the resilient wrapper can retry.
                logger.warning(
                    "JSON parse failed despite completeness check passing "
                    "(stop_reason=%s, len=%d): %s",
                    stop_reason,
                    len(accumulated_text),
                    e,
                    extra={"event_code": "llm.json_parse_failed"},
                )
                yield {
                    "type": "truncation_warning",
                    "accumulated_text": accumulated_text,
                }
            except Exception as e:
                logger.error(
                    "Formulation validation failed: %s",
                    e,
                    exc_info=True,
                    extra={"event_code": "llm.formulation_validation_failed"},
                )
                yield {"type": "error", "code": LLMErrorCode.INTERNAL_ERROR}

    except Exception as e:
        yield handle_anthropic_failure(e, logger=logger, context="formulation stream")

    # W17: report this attempt's real token usage — also after an upstream
    # error, because partial usage was still billed. Internal event: the SSE
    # endpoint accumulates it for cost persistence; never sent to clients.
    if usage_input_tokens or usage_output_tokens:
        yield {
            "type": "usage",
            "model": model,
            "input_tokens": usage_input_tokens,
            "output_tokens": usage_output_tokens,
        }

    yield {"type": "done"}


async def generate_formulation_resilient(
    messages: list[dict[str, Any]],
    model: str,
    thinking: bool = False,
    user_message: str = "",
    system_prompt: str | None = None,
    db: Any | None = None,
    client: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Resilient formulation generator with auto-retry on truncation.

    Wraps generate_formulation with escalating max_tokens:
    1. Dynamic estimate from user_message
    2. 2x max_tokens on first truncation
    3. 4x max_tokens on second truncation
    4. Yields needs_chunking signal if all retries exhausted

    Args:
        messages: Anthropic API messages list.
        model: Model ID.
        thinking: Whether to use extended thinking.
        user_message: Original user message for dynamic token estimation.
        db: Optional DB session for runtime settings.

    Yields:
        Event dicts for SSE streaming.
    """
    llm_max_tokens = _pss_int(db, "LLM_MAX_TOKENS")
    llm_max_retries = _pss_int(db, "LLM_MAX_RETRIES")
    llm_output_limit = _pss_int(db, "LLM_MAX_OUTPUT_TOKENS_LIMIT")

    estimated = estimate_output_tokens(user_message, db=db)
    max_tokens = max(llm_max_tokens, estimated)
    max_attempts = 1 + llm_max_retries  # original + retries

    for attempt in range(max_attempts):
        # Cap at model limit
        capped_tokens = min(max_tokens, llm_output_limit)
        is_first_attempt = attempt == 0

        truncated = False
        got_formulation = False

        async for event in generate_formulation(
            messages,
            model,
            thinking,
            max_tokens=capped_tokens,
            system_prompt=system_prompt,
            db=db,
            client=client,
        ):
            event_type = event.get("type", "")

            if event_type == "truncation_warning":
                truncated = True
                continue
            elif event_type == "done":
                if truncated:
                    # Don't yield done yet -- we'll retry
                    continue
                if got_formulation:
                    # Success -- yield done and return
                    yield event
                    return
                # Error path -- done without formulation or truncation
                yield event
                return
            elif event_type == "formulation":
                got_formulation = True
                yield event
            elif event_type == "delta" and is_first_attempt:
                # Only stream deltas on the first attempt for UX.
                # On retries the client already has partial text;
                # we just send status + final formulation.
                yield event
            elif event_type not in ("delta",):
                # Pass through error, validation_errors, etc.
                yield event

        if not truncated:
            # No truncation and no formulation -- error was yielded already
            return

        # Truncation detected -- escalate max_tokens
        max_tokens = capped_tokens * 2

        if attempt < max_attempts - 1:
            # Emit a generic "still generating" status — the token budget
            # and retry counter are internal details that the user must not
            # see. Full detail goes to logs + metrics for admin visibility.
            yield {"type": "status", "code": LLMStatusCode.GENERATING}
            logger.info(
                "Truncation retry %d: escalating max_tokens from %d to %d",
                attempt + 1,
                capped_tokens,
                capped_tokens * 2,
                extra={"event_code": "llm.truncation_retry"},
            )
            LLM_RETRIES_TOTAL.labels(reason="truncation").inc()

    # All retries exhausted -- fall through to chunked generation.
    # Do not emit a synthetic GENERATING status here: generate_formulation_chunked
    # yields GENERATING_VARIABLES as its first event, so an extra GENERATING
    # would just flash-and-disappear in the UI.
    logger.warning(
        "All retries exhausted, falling back to chunked generation",
        extra={"event_code": "llm.chunked_fallback"},
    )
    LLM_RETRIES_TOTAL.labels(reason="chunked_fallback").inc()
    from app.services.llm.chunked_generation import generate_formulation_chunked

    async for event in generate_formulation_chunked(
        messages, model, thinking, db=db, client=client
    ):
        yield event


async def generate_text_response(
    messages: list[dict[str, Any]],
    model: str,
    thinking: bool = False,
    system_prompt: str | None = None,
    db: Any | None = None,
    client: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Generate a plain-text response (no structured JSON schema).

    Used for explanation mode (e.g. failure explanations). Streams raw
    text deltas without forcing JSON output.

    Args:
        messages: Anthropic API messages list (from build_messages).
        model: Model ID to use.
        thinking: Whether to enable extended thinking.
        db: Optional DB session for runtime settings.

    Yields:
        Event dicts: {"type": "delta", "text": "..."} and {"type": "done"}.
    """
    # BYOK: use the org-resolved client when provided, else the platform client.
    client = client or get_anthropic_client(db=db)

    llm_max_tokens = _pss_int(db, "LLM_MAX_TOKENS")

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": llm_max_tokens,
        "system": system_prompt or FORMULATION_SYSTEM_PROMPT,
        "messages": messages,
    }

    if thinking:
        thinking_budget = _pss_int(db, "LLM_THINKING_BUDGET_TOKENS")
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_budget,
        }

    usage_input_tokens = 0
    usage_output_tokens = 0

    try:
        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                # W17: real token usage (same capture as generate_formulation).
                if event.type == "message_start":
                    _usage = getattr(getattr(event, "message", None), "usage", None)
                    _in = getattr(_usage, "input_tokens", None)
                    if isinstance(_in, int):
                        usage_input_tokens = _in
                    continue
                if event.type == "message_delta":
                    _out = getattr(getattr(event, "usage", None), "output_tokens", None)
                    if isinstance(_out, int):
                        usage_output_tokens = _out
                    continue
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "type") and event.delta.type == "thinking_delta":
                        continue
                    if hasattr(event.delta, "text"):
                        yield {"type": "delta", "text": event.delta.text}

    except Exception as e:
        yield handle_anthropic_failure(e, logger=logger, context="text response stream")

    if usage_input_tokens or usage_output_tokens:
        yield {
            "type": "usage",
            "model": model,
            "input_tokens": usage_input_tokens,
            "output_tokens": usage_output_tokens,
        }

    yield {"type": "done"}
