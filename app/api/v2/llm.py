"""LLM conversation and streaming endpoints.

Provides:
- POST /conversations — Create a new conversation
- GET /conversations — List active conversations (paginated)
- GET /conversations/{conversation_id} — Get conversation with messages
- DELETE /conversations/{conversation_id} — Delete a conversation
- POST /conversations/{conversation_id}/messages — Send message and stream SSE response
- POST /conversations/{conversation_id}/attachments — Upload document attachment
- DELETE /conversations/{conversation_id}/attachments/{attachment_id} — Delete attachment
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequestLocale
from app.domains.solver import scenario_job
from app.models import ModelExecution
from app.models.conversation_attachment import ConversationAttachment
from app.models.llm_conversation import LLMConversation, LLMMessage
from app.schemas.attachment import AttachmentResponse
from app.schemas.llm import (
    ChatMessageRequest,
    ExplainInfeasibilityRequest,
    ExplainModelRequest,
    ExplainScenariosRequest,
    ExplainSolutionRequest,
    ExplainVersionDiffRequest,
)
from app.schemas.optimization import ScenarioExplanationResponse
from app.services.document_extraction import MAX_FILE_SIZE, extract_text
from app.services.llm import (
    explain_infeasibility,
    explain_model,
    explain_scenarios,
    explain_solution,
    explain_version_diff,
    generate_formulation_resilient,
    generate_text_response,
    moderate_message,
    select_model,
)
from app.services.llm.anthropic_client import get_anthropic_client
from app.services.llm.byok import resolve_anthropic_client
from app.services.llm.cost_tracking import (
    LEDGER_MODEL_ID_PREFIX,
    compute_message_cost_eur,
    is_llm_budget_exceeded,
    record_standalone_llm_spend,
)
from app.services.llm.errors import (
    LLMErrorCode,
    LLMStatusCode,
    handle_anthropic_failure,
)
from app.services.llm.prompt_templates import build_messages, build_system_prompt
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.prometheus_metrics import LLM_REQUESTS_TOTAL
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import create_paginated_response, paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


class CreateConversationRequest(BaseModel):
    """Request body for creating a new conversation."""

    template_id: str | None = Field(
        None, description="Template ID for template-based conversations"
    )
    model_id: str | None = Field(None, description="Builder document ID for conversation scoping")
    model_project_id: str | None = Field(
        None, description="ModelProject id (studio) for conversation scoping"
    )


def _problem_to_formulation(problem: dict[str, Any], name: str) -> dict[str, Any]:
    """Map a canonical ``OptimizationProblem`` to a ``Formulation`` dict.

    Seeds a studio conversation's ``current_formulation`` from the project's current
    model, so the first chat message refines the EXISTING model instead of starting
    from scratch. Structural copy only; descriptions default to empty.
    """
    variables = [
        {
            "name": v.get("name", ""),
            "type": v.get("type", "continuous"),
            "lower_bound": v.get("lower_bound"),
            "upper_bound": v.get("upper_bound"),
            "description": v.get("description", ""),
        }
        for v in (problem.get("variables") or [])
    ]
    constraints = [
        {
            "name": c.get("name", ""),
            "expression": c.get("expression", ""),
            "description": c.get("description", ""),
        }
        for c in (problem.get("constraints") or [])
    ]
    obj = problem.get("objective") or {}
    return {
        "problem_name": name or "Model",
        "summary": "",
        "variables": variables,
        "constraints": constraints,
        "objective": {
            "sense": obj.get("sense", "minimize"),
            "expression": obj.get("expression", ""),
            "description": obj.get("description", ""),
        },
    }


def _is_real_formulation(formulation: dict[str, Any] | None) -> bool:
    """Whether a generated formulation is a real model worth persisting.

    A refusal (``problem_name == "not_applicable"``) or an empty/variable-less
    formulation must NOT overwrite an existing model — that would erase the user's
    work. A meaningful optimization model always has at least one variable.
    """
    if not formulation:
        return False
    if formulation.get("problem_name") == "not_applicable":
        return False
    return bool(formulation.get("variables"))


def _get_conversation_or_404(
    db: Session,
    conversation_id: str,
    org_id: str,
    user_id: str,
) -> LLMConversation:
    """Load a conversation, verify ownership, and check expiry.

    Raises:
        HTTPException 404 if not found, not owned, or expired.
    """
    conv = (
        db.query(LLMConversation)
        .options(joinedload(LLMConversation.messages))
        .filter(
            LLMConversation.id == conversation_id,
            LLMConversation.organization_id == org_id,
            LLMConversation.user_id == user_id,
        )
        .first()
    )

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conv.expires_at < utcnow():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation has expired",
        )

    return conv


def _conv_to_response(conv: LLMConversation, include_messages: bool = True) -> dict[str, Any]:
    """Convert a conversation ORM object to a response dict."""
    data: dict[str, Any] = {
        "id": conv.id,
        "created_at": conv.created_at.isoformat(),
        "expires_at": conv.expires_at.isoformat(),
        "current_formulation": conv.current_formulation,
        "model_id": conv.model_id,
        "model_project_id": conv.model_project_id,
    }
    if include_messages:
        data["messages"] = [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "formulation_json": msg.formulation_json,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in sorted(conv.messages, key=lambda m: m.created_at)
        ]
    else:
        data["messages"] = []
    return data


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: CreateConversationRequest,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> dict[str, Any]:
    """Create a new LLM conversation.

    A studio conversation (``model_project_id``) is seeded with the project's
    current model so the first message refines it. Requires the
    ``llm_assistant`` feature in the organization's plan.
    """
    from datetime import timedelta

    # Feature gate: check that the org's plan includes llm_assistant
    plan_config = PSS.get_plan_config_dynamic(db, org.plan)
    if "llm_assistant" not in plan_config.get("allowed_features", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": "The LLM assistant is not available on your current plan.",
                "plan": org.plan,
            },
        )

    # Studio scoping: a model_project_id must reference an org-owned project (404 otherwise).
    project = None
    if body.model_project_id:
        from app.services import model_project_service as projects_svc

        project = projects_svc.get_project_or_404(db, body.model_project_id, org.id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model project not found",
            )

    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=org.id,
        user_id=user.id,
        template_id=body.template_id,
        model_id=body.model_id,
        model_project_id=body.model_project_id,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=PSS.get_int(db, "LLM_CONVERSATION_TTL_HOURS")),
    )

    if project is not None:
        # Seed the conversation with the project's current model so the first chat
        # message refines the EXISTING model rather than generating from scratch.
        draft = project.draft_model_json or {}
        if draft.get("variables"):
            conv.current_formulation = _problem_to_formulation(draft, project.name)

    db.add(conv)
    db.commit()
    db.refresh(conv)

    return _conv_to_response(conv)


@router.get("/conversations")
def list_conversations(
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    model_id: str | None = Query(None, description="Filter by builder document ID"),
    model_project_id: str | None = Query(None, description="Filter by ModelProject id (studio)"),
) -> dict[str, Any]:
    """List active (non-expired) conversations for the current user."""
    now = utcnow()
    query = (
        db.query(LLMConversation)
        .filter(
            LLMConversation.organization_id == org.id,
            LLMConversation.user_id == user.id,
            LLMConversation.expires_at > now,
            # Hide internal bookkeeping conversations (e.g. the B3 JModel-AI cost
            # ledger), which use a "sys:" model_id sentinel and carry no user chat.
            or_(
                LLMConversation.model_id.is_(None),
                ~LLMConversation.model_id.startswith(LEDGER_MODEL_ID_PREFIX),
            ),
        )
        .order_by(LLMConversation.created_at.desc())
    )

    if model_id:
        query = query.filter(LLMConversation.model_id == model_id)
    if model_project_id:
        query = query.filter(LLMConversation.model_project_id == model_project_id)

    items, total = paginate_query(query, page=page, page_size=page_size)

    response_items = [_conv_to_response(conv, include_messages=False) for conv in items]
    return create_paginated_response(response_items, total, page, page_size)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> dict[str, Any]:
    """Get a conversation with all its messages."""
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)
    return _conv_to_response(conv)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> None:
    """Delete a conversation and all its messages (CASCADE)."""
    conv = (
        db.query(LLMConversation)
        .filter(
            LLMConversation.id == conversation_id,
            LLMConversation.organization_id == org.id,
            LLMConversation.user_id == user.id,
        )
        .first()
    )

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    db.delete(conv)
    db.commit()
    return


async def _stream_llm_response(
    *,
    stream_gen: AsyncGenerator[dict[str, Any], None],
    request: Request,
    db: Session,
    conv: LLMConversation,
    org_id: str,
    model: str,
    request_id: str,
    is_explanation: bool,
    bill_platform: bool = True,
) -> AsyncGenerator[dict[str, str], None]:
    """Forward an LLM event stream as SSE, with EUR cost accounting.

    Shared by the chat (``send_message``) and ``explain-*`` endpoints so the SSE
    event contract and real-token cost persistence stay byte-for-byte identical
    across all of them. On success the assistant message is persisted with its
    token usage and EUR cost.

    When ``bill_platform`` is False (BYOK — the org ran on its own Anthropic key)
    ``cost_eur`` is left NULL so the run never counts against the platform's
    monthly AI budget.
    """
    accumulated_text = ""
    formulation_data = None
    stream_failed = False  # Track whether we saw a non-recoverable error event
    # W17: real token usage accumulated across ALL API calls this message
    # triggered (retries and chunked-generation calls each bill separately).
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        async for event in stream_gen:
            if await request.is_disconnected():
                logger.info("Client disconnected, stopping stream")
                break

            event_type = event.get("type", "unknown")

            if event_type == "delta":
                accumulated_text += event.get("text", "")
                yield {
                    "event": "delta",
                    "data": json.dumps({"text": event["text"]}),
                }
            elif event_type == "usage":
                # W17: internal-only token accounting — persisted on the
                # assistant LLMMessage below, never sent to the client.
                total_input_tokens += int(event.get("input_tokens") or 0)
                total_output_tokens += int(event.get("output_tokens") or 0)
            elif event_type == "formulation":
                formulation_data = event.get("data")
                yield {
                    "event": "formulation",
                    "data": json.dumps({"formulation": formulation_data}),
                }
            elif event_type == "validation_errors":
                yield {
                    "event": "validation_errors",
                    "data": json.dumps({"errors": event.get("data", [])}),
                }
            elif event_type == "status":
                # Only stable enum codes travel to the client. Any
                # event that does not carry a valid LLMStatusCode is
                # dropped with a warning so upstream regressions that
                # silently drop the ``code`` kwarg become visible in
                # logs instead of vanishing from the UI.
                code = event.get("code")
                if isinstance(code, LLMStatusCode):
                    yield {
                        "event": "status",
                        "data": json.dumps({"code": code.value, "request_id": request_id}),
                    }
                else:
                    logger.warning(
                        "Status event dropped (missing or invalid code: %r)",
                        code,
                        extra={
                            "event_code": "llm.status_dropped",
                            "request_id": request_id,
                        },
                    )
            elif event_type == "partial_result":
                formulation_data = event.get("data")
                yield {
                    "event": "partial_result",
                    "data": json.dumps(
                        {
                            "formulation": formulation_data,
                            "warning": event.get("warning", ""),
                        }
                    ),
                }
            elif event_type == "error":
                stream_failed = True
                # Fall back to INTERNAL_ERROR if an upstream producer
                # ever yields a legacy ``message`` field — never leak
                # a free-form string into the SSE payload.
                code = event.get("code")
                if not isinstance(code, LLMErrorCode):
                    code = LLMErrorCode.INTERNAL_ERROR
                yield {
                    "event": "error",
                    "data": json.dumps({"code": code.value, "request_id": request_id}),
                }
            elif event_type == "done":
                # The done event always fires after error because
                # generate_formulation yields {"type": "done"}
                # unconditionally even on failure.
                LLM_REQUESTS_TOTAL.labels(outcome="error" if stream_failed else "success").inc()
                if not stream_failed:
                    # Persist assistant message after stream completes
                    try:
                        # W17: price the real token usage via the
                        # per-model pricing map (platform setting).
                        # NULL columns mean "usage was never captured"
                        # (pre-migration rows / providers without usage),
                        # not "zero tokens".
                        has_usage = bool(total_input_tokens or total_output_tokens)
                        # BYOK (bill_platform=False): the spend is on the org's own
                        # account, so cost_eur stays NULL and never counts toward the
                        # platform's monthly AI budget (is_llm_budget_exceeded).
                        message_cost = (
                            compute_message_cost_eur(
                                db, model, total_input_tokens, total_output_tokens
                            )
                            if (has_usage and bill_platform)
                            else None
                        )
                        assistant_msg = LLMMessage(
                            id=generate_id("msg_"),
                            conversation_id=conv.id,
                            role="assistant",
                            content=accumulated_text,
                            formulation_json=formulation_data,
                            input_tokens=total_input_tokens if has_usage else None,
                            output_tokens=total_output_tokens if has_usage else None,
                            cost_eur=message_cost,
                            created_at=utcnow(),
                        )
                        db.add(assistant_msg)

                        # Update conversation's current formulation (only for real
                        # formulation responses, not explanations). A refusal/empty
                        # formulation must never overwrite a good existing model.
                        if not is_explanation and _is_real_formulation(formulation_data):
                            conv.current_formulation = formulation_data

                        db.commit()
                    except Exception as e:
                        logger.error("Failed to persist assistant message: %s", e)
                        db.rollback()

                yield {
                    "event": "done",
                    "data": "{}",
                }

    except Exception as e:
        # Never leak str(e) — the raw exception may contain upstream
        # API detail (Anthropic error bodies, DB errors, stack traces).
        # handle_anthropic_failure classifies, logs, and bumps the
        # upstream-error counter in one call.
        LLM_REQUESTS_TOTAL.labels(outcome="error").inc()
        error_event = handle_anthropic_failure(
            e,
            logger=logger,
            context="SSE stream wrapper",
            request_id=request_id,
        )
        code = error_event["code"]
        yield {
            "event": "error",
            "data": json.dumps({"code": code.value, "request_id": request_id}),
        }


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> Any:
    """Send a message and stream the LLM response as SSE events.

    The endpoint:
    1. Validates conversation ownership and expiry
    2. Runs content moderation pre-check
    3. Persists the user message
    4. Streams the LLM response as SSE events (delta, formulation, validation_errors, done)
    5. Persists the assistant message after streaming completes
    """
    # Verify conversation exists and is not expired
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)

    # BYOK: when the org has its own Anthropic key, the call runs on their account —
    # so the platform budget guardrail below is skipped.
    byok_client, is_byok = resolve_anthropic_client(org)

    # W17 budget guardrail: pause the assistant gracefully when the
    # platform's monthly Anthropic budget (LLM_MONTHLY_BUDGET_EUR) is
    # exhausted. Same friendly feature-disabled shape as the plan feature
    # gate in create_conversation so the UI degrades identically. The check
    # is cached in-process (~60s) — no per-message SUM aggregation.
    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's "
                    "monthly AI budget has been reached. It will be back at the "
                    "start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    # LLM rate limiting
    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    # Content moderation pre-check
    is_allowed, rejection_msg = moderate_message(body.message)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=rejection_msg,
        )

    # Persist user message
    user_msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="user",
        content=body.message,
        created_at=utcnow(),
    )
    db.add(user_msg)
    db.commit()

    # Fire-and-forget: log ai_builder.message analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=user.id,
            org_id=org.id,
            event_type=evt.AI_BUILDER_MESSAGE,
            ip_address=request.client.host if request.client else None,
            metadata={"conversation_id": conversation_id},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    attachment = (
        db.query(ConversationAttachment)
        .filter(ConversationAttachment.conversation_id == conversation_id)
        .first()
    )
    document_context = None
    if attachment:
        document_context = {
            "filename": attachment.filename,
            "char_count": attachment.char_count,
            "extracted_text": attachment.extracted_text,
        }

    # Build message history for Anthropic API (with refinement context)
    history = [
        {"role": msg.role, "content": msg.content, "formulation_json": msg.formulation_json}
        for msg in sorted(conv.messages, key=lambda m: m.created_at)
    ]
    api_messages = build_messages(
        history,
        body.message,
        latest_formulation=conv.current_formulation,
        document_context=document_context,
    )

    # Retrieve RAG context (best-effort, never blocks formulation)
    rag_context = None
    try:
        from app.services.rag.retriever import get_rag_context

        rag_context = await get_rag_context(
            body.message,
            db,
            current_formulation=conv.current_formulation,
        )
    except Exception:
        logger.debug("RAG context retrieval skipped", exc_info=True)

    # Build system prompt (with RAG context and document attachment)
    system_prompt = build_system_prompt(document_context, rag_context=rag_context, locale=locale)

    # Select model
    model, use_thinking = select_model(body.use_advanced_model, db=db)

    # Choose generator based on response_type
    is_explanation = body.response_type == "explanation"

    # Request id is set by RequestIdMiddleware and echoed back to clients
    # in every status/error SSE event so support can correlate chat-side
    # complaints with server logs and Prometheus metrics.
    request_id = getattr(request.state, "request_id", None) or ""

    # Select the appropriate generator. byok_client is non-None only for BYOK orgs;
    # otherwise the generators create the platform client internally.
    if is_explanation:
        stream_gen = generate_text_response(
            api_messages,
            model,
            use_thinking,
            system_prompt=system_prompt,
            client=byok_client,
            db=db,
        )
    else:
        stream_gen = generate_formulation_resilient(
            api_messages,
            model,
            use_thinking,
            user_message=body.message,
            system_prompt=system_prompt,
            client=byok_client,
            db=db,
        )

    return EventSourceResponse(
        _stream_llm_response(
            stream_gen=stream_gen,
            request=request,
            db=db,
            conv=conv,
            org_id=org.id,
            model=model,
            request_id=request_id,
            is_explanation=is_explanation,
            bill_platform=not is_byok,
        )
    )


def _resolve_explanation_context(
    db: Session,
    org_id: str,
    body: ExplainSolutionRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve (formulation, solution, sensitivity) for an explanation request.

    ``execution_id`` takes precedence: the ModelExecution is loaded and org
    ownership enforced (404 if missing or owned by another org — never leak the
    existence of another org's execution). Falls back to the inline request fields
    when no ``execution_id`` is supplied.
    """
    if body.execution_id:
        from app.models.optimization_model import ModelExecution

        execution = (
            db.query(ModelExecution)
            .filter(
                ModelExecution.id == body.execution_id,
                ModelExecution.organization_id == org_id,
            )
            .first()
        )
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Execution not found",
            )
        result_data = execution.result_data or {}
        # result_data follows OptimizationResult.to_result_data(): model (the
        # variable->value dict), objective_value, solver_status, variables,
        # sensitivity, progress_history.
        solution = {
            "objective_value": result_data.get("objective_value"),
            "solution": result_data.get("model"),
            "variables": result_data.get("variables"),
            "solver_status": result_data.get("solver_status"),
        }
        sensitivity = result_data.get("sensitivity")
        return execution.input_data or None, solution, sensitivity

    return body.formulation, body.solution, body.sensitivity


@router.post("/conversations/{conversation_id}/explain-solution")
async def explain_solution_endpoint(
    conversation_id: str,
    body: ExplainSolutionRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> Any:
    """Stream a plain-language explanation of a solved optimization model as SSE.

    Loads the solution + sensitivity from a persisted ModelExecution
    (``execution_id``, org ownership enforced) or from inline fields, then reuses
    the chat streaming pipeline — budget guardrail, org rate limit
    (refunded on failure), a persisted user/assistant turn pair — driven by
    ``explain_solution`` rather than formulation generation. Moderation is skipped
    because the prompt content is system-generated, not free user text.
    """
    # Verify conversation ownership and expiry
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)

    # BYOK: org with its own key runs on their account — skip the budget guardrail.
    byok_client, is_byok = resolve_anthropic_client(org)

    # W17 budget guardrail — pause gracefully when the monthly Anthropic budget
    # is exhausted (identical shape to send_message so the UI degrades the same).
    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's "
                    "monthly AI budget has been reached. It will be back at the "
                    "start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    # LLM rate limiting (shared org bucket with chat)
    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    # Resolve what to explain (execution ownership enforced here) up front, so an
    # invalid execution_id fails cleanly.
    formulation, solution, sensitivity = _resolve_explanation_context(db, org.id, body)
    if not solution and not formulation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No solution to explain — provide execution_id or inline solution.",
        )

    # Persist a user turn marking the explanation request. The content is
    # system-generated scaffolding (the grounded prompt is built server-side),
    # so content moderation does not apply here.
    user_msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="user",
        content="Explain this solution",
        created_at=utcnow(),
    )
    db.add(user_msg)
    db.commit()

    model, use_thinking = select_model(body.use_advanced_model, db=db)
    request_id = getattr(request.state, "request_id", None) or ""

    stream_gen = explain_solution(
        [],
        formulation,
        solution,
        sensitivity,
        model,
        thinking=use_thinking,
        locale=locale,
        client=byok_client,
        db=db,
    )
    return EventSourceResponse(
        _stream_llm_response(
            stream_gen=stream_gen,
            request=request,
            db=db,
            conv=conv,
            org_id=org.id,
            model=model,
            request_id=request_id,
            is_explanation=True,
            bill_platform=not is_byok,
        )
    )


def _resolve_infeasibility_context(
    db: Session,
    org_id: str,
    body: ExplainInfeasibilityRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve (formulation, infeasibility) for an explain-infeasibility request.

    ``execution_id`` takes precedence: the ModelExecution is loaded and org
    ownership enforced (404 if missing or owned by another org — never leak the
    existence of another org's execution). The formulation is the persisted
    ``input_data`` and the IIS comes from ``result_data.infeasibility_analysis``
    (may be absent → heuristic explanation). Falls back to the inline request
    fields when no ``execution_id`` is supplied.
    """
    if body.execution_id:
        from app.models.optimization_model import ModelExecution

        execution = (
            db.query(ModelExecution)
            .filter(
                ModelExecution.id == body.execution_id,
                ModelExecution.organization_id == org_id,
            )
            .first()
        )
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Execution not found",
            )
        result_data = execution.result_data or {}
        infeasibility = result_data.get("infeasibility_analysis")
        return execution.input_data or None, infeasibility

    return body.formulation, body.infeasibility


@router.post("/conversations/{conversation_id}/explain-infeasibility")
async def explain_infeasibility_endpoint(
    conversation_id: str,
    body: ExplainInfeasibilityRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> Any:
    """Stream a plain-language explanation of WHY a model is INFEASIBLE as SSE.

    Loads the formulation + persisted IIS from a ModelExecution (``execution_id``,
    org ownership enforced) or from inline fields, then reuses the chat streaming
    pipeline — budget guardrail, org rate limit (refusals surface on
    failure), a persisted user/assistant turn pair — driven by
    ``explain_infeasibility``. When no IIS is available the explanation is heuristic
    and clearly flagged. Moderation is skipped because the prompt content is
    system-generated, not free user text.
    """
    # Verify conversation ownership and expiry
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)

    # BYOK: org with its own key runs on their account — skip the budget guardrail.
    byok_client, is_byok = resolve_anthropic_client(org)

    # W17 budget guardrail — pause gracefully when the monthly Anthropic budget
    # is exhausted (identical shape to send_message so the UI degrades the same).
    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's "
                    "monthly AI budget has been reached. It will be back at the "
                    "start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    # LLM rate limiting (shared org bucket with chat)
    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    # Resolve what to explain (execution ownership enforced here) up front, so an
    # invalid execution_id fails cleanly.
    formulation, infeasibility = _resolve_infeasibility_context(db, org.id, body)
    if not formulation and not infeasibility:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nothing to explain — provide execution_id or inline formulation.",
        )

    # Persist a user turn marking the explanation request. The content is
    # system-generated scaffolding (the grounded prompt is built server-side),
    # so content moderation does not apply here.
    user_msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="user",
        content="Explain why this model is infeasible",
        created_at=utcnow(),
    )
    db.add(user_msg)
    db.commit()

    model, use_thinking = select_model(body.use_advanced_model, db=db)
    request_id = getattr(request.state, "request_id", None) or ""

    stream_gen = explain_infeasibility(
        [],
        formulation,
        infeasibility,
        model,
        thinking=use_thinking,
        locale=locale,
        client=byok_client,
        db=db,
    )
    return EventSourceResponse(
        _stream_llm_response(
            stream_gen=stream_gen,
            request=request,
            db=db,
            conv=conv,
            org_id=org.id,
            model=model,
            request_id=request_id,
            is_explanation=True,
            bill_platform=not is_byok,
        )
    )


def _resolve_model_explanation_context(
    db: Session,
    org_id: str,
    body: ExplainModelRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve (formulation, stats) for an explain-model request.

    ``project_id`` takes precedence: the ModelProject is loaded with org ownership
    enforced (404 if missing or owned by another org — never leak existence). A
    ``version_id`` explains that committed snapshot (formulation + its frozen
    ``stats_json``); otherwise the project's mutable draft is explained, with stats
    computed live. Falls back to the inline ``formulation`` (``stats`` computed when
    omitted) when no ``project_id`` is supplied.
    """
    if body.project_id:
        from app.services import model_project_service as projects_svc
        from app.services.model_stats_service import compute_from_json

        project = projects_svc.get_project_or_404(db, body.project_id, org_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if body.version_id:
            version = projects_svc.get_version_or_404(db, body.project_id, body.version_id, org_id)
            if not version:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Version not found"
                )
            return version.model_json, version.stats_json
        draft = project.draft_model_json
        stats = compute_from_json(draft).model_dump(mode="json") if draft else None
        return draft, stats

    formulation = body.formulation
    stats = body.stats
    if formulation and not stats:
        from app.services.model_stats_service import compute_from_json

        stats = compute_from_json(formulation).model_dump(mode="json")
    return formulation, stats


@router.post("/conversations/{conversation_id}/explain-model")
async def explain_model_endpoint(
    conversation_id: str,
    body: ExplainModelRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> Any:
    """Stream a plain-language explanation of an optimization MODEL (not yet solved) as SSE.

    Loads the formulation + the Python-computed ``ModelStats`` from a ModelProject
    (``project_id``, draft or a committed ``version_id``, org ownership enforced) or
    from inline fields, then reuses the chat streaming pipeline — budget guardrail,
    org rate limit, a persisted user/assistant
    turn pair — driven by ``explain_model``. The statistics are authoritative, so the
    explanation has nothing to fabricate. Moderation is skipped because the prompt
    content is system-generated, not free user text.
    """
    # Verify conversation ownership and expiry
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)

    # BYOK: org with its own key runs on their account — skip the budget guardrail.
    byok_client, is_byok = resolve_anthropic_client(org)

    # W17 budget guardrail — pause gracefully when the monthly Anthropic budget is exhausted.
    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's "
                    "monthly AI budget has been reached. It will be back at the "
                    "start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    # LLM rate limiting (shared org bucket with chat)
    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    # Resolve what to explain (project/version ownership enforced here) up front,
    # so an invalid project/version fails cleanly.
    formulation, stats = _resolve_model_explanation_context(db, org.id, body)
    if not formulation:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No model to explain — provide project_id or inline formulation.",
        )

    user_msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="user",
        content="Explain this model",
        created_at=utcnow(),
    )
    db.add(user_msg)
    db.commit()

    model, use_thinking = select_model(body.use_advanced_model, db=db)
    request_id = getattr(request.state, "request_id", None) or ""

    stream_gen = explain_model(
        [],
        formulation,
        stats,
        model,
        thinking=use_thinking,
        locale=locale,
        client=byok_client,
        db=db,
    )
    return EventSourceResponse(
        _stream_llm_response(
            stream_gen=stream_gen,
            request=request,
            db=db,
            conv=conv,
            org_id=org.id,
            model=model,
            request_id=request_id,
            is_explanation=True,
            bill_platform=not is_byok,
        )
    )


def _resolve_diff_explanation_context(
    db: Session,
    org_id: str,
    body: ExplainVersionDiffRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any], str | None, str | None]:
    """Resolve (old_problem, new_problem, structural_diff, old_summary, new_summary).

    The project and BOTH versions are loaded with org ownership enforced (404 on any
    miss — never leak another org's data). The structural diff is computed in Python
    (``model_project_service.diff_versions``); the LLM only narrates it, so the
    explanation is hallucination-proof.
    """
    from app.services import model_project_service as projects_svc

    project = projects_svc.get_project_or_404(db, body.project_id, org_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    v_from = projects_svc.get_version_or_404(db, body.project_id, body.from_version_id, org_id)
    v_to = projects_svc.get_version_or_404(db, body.project_id, body.to_version_id, org_id)
    if not v_from or not v_to:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    diff = projects_svc.diff_versions(v_from, v_to)
    return (
        v_from.model_json,
        v_to.model_json,
        diff.model_dump(mode="json"),
        v_from.commit_summary,
        v_to.commit_summary,
    )


@router.post("/conversations/{conversation_id}/explain-diff")
async def explain_diff_endpoint(
    conversation_id: str,
    body: ExplainVersionDiffRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
) -> Any:
    """Stream a plain-language narration of the CHANGE between two model versions as SSE.

    Loads the project + both versions (org ownership enforced), computes the structural
    diff server-side via ``model_project_service.diff_versions``, and reuses the chat
    streaming pipeline (budget guardrail, rate limit, refusals surfaced on
    failure, persisted turn pair) driven by ``explain_version_diff``. The LLM narrates
    ONLY the pre-computed diff. Moderation is skipped (system-generated prompt content).
    """
    conv = _get_conversation_or_404(db, conversation_id, org.id, user.id)

    byok_client, is_byok = resolve_anthropic_client(org)

    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's "
                    "monthly AI budget has been reached. It will be back at the "
                    "start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    # Resolve + compute the diff (ownership enforced) up front — an invalid
    # version reference fails cleanly before any message is persisted.
    old_problem, new_problem, structural_diff, old_summary, new_summary = (
        _resolve_diff_explanation_context(db, org.id, body)
    )

    user_msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv.id,
        role="user",
        content="Explain the change between these versions",
        created_at=utcnow(),
    )
    db.add(user_msg)
    db.commit()

    model, use_thinking = select_model(body.use_advanced_model, db=db)
    request_id = getattr(request.state, "request_id", None) or ""

    stream_gen = explain_version_diff(
        [],
        old_problem,
        new_problem,
        structural_diff,
        old_summary,
        new_summary,
        model,
        thinking=use_thinking,
        locale=locale,
        client=byok_client,
        db=db,
    )
    return EventSourceResponse(
        _stream_llm_response(
            stream_gen=stream_gen,
            request=request,
            db=db,
            conv=conv,
            org_id=org.id,
            model=model,
            request_id=request_id,
            is_explanation=True,
            bill_platform=not is_byok,
        )
    )


# Extension-to-MIME mapping for allowed document types
_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".txt": "text/plain",
}


@router.post("/conversations/{conversation_id}/attachments")
def upload_attachment(  # sync ON PURPOSE -> threadpool (ADR-009): PDF text extraction
    conversation_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    file: UploadFile = File(...),
) -> AttachmentResponse:
    """Upload a document attachment to a conversation.

    Accepts PDF, CSV, or TXT files. Extracts text content and stores
    metadata. Replaces any existing attachment (one per conversation).
    """
    # Verify conversation ownership
    _get_conversation_or_404(db, conversation_id, org.id, user.id)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _EXT_TO_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: .pdf, .csv, .txt",
        )
    content_type = _EXT_TO_MIME[ext]

    # Read and validate content size
    # Read the already-spooled upload directly (Starlette buffers it before the
    # handler runs): extracting text from a PDF is CPU-bound and has no business on
    # the event loop (ADR-009).
    content = file.file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty",
        )
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    # Extract text
    try:
        result = extract_text(content, file.filename or "unknown", content_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from None

    # Replace existing attachment (one-per-conversation rule)
    existing = (
        db.query(ConversationAttachment)
        .filter(ConversationAttachment.conversation_id == conversation_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    attachment = ConversationAttachment(
        conversation_id=conversation_id,
        filename=file.filename or "unknown",
        mime_type=result.mime_type,
        char_count=result.char_count,
        preview=result.preview,
        extracted_text=result.text,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    return AttachmentResponse.model_validate(attachment)


@router.delete(
    "/conversations/{conversation_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attachment(
    conversation_id: str,
    attachment_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> None:
    """Delete a document attachment from a conversation."""
    # Verify conversation ownership
    _get_conversation_or_404(db, conversation_id, org.id, user.id)

    attachment = (
        db.query(ConversationAttachment)
        .filter(
            ConversationAttachment.id == attachment_id,
            ConversationAttachment.conversation_id == conversation_id,
        )
        .first()
    )
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    db.delete(attachment)
    db.commit()
    return


@router.post(
    "/executions/{execution_id}/explain-scenarios",
    operation_id="explain_execution_scenarios",
)
async def explain_execution_scenarios(
    execution_id: str,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    locale: RequestLocale,
    body: ExplainScenariosRequest | None = None,
) -> ScenarioExplanationResponse:
    """Read a finished what-if analysis (Sensitivity L2) back in plain language.

    Narrates scenarios that were MEASURED by re-solving — the system prompt
    forbids inventing a scenario that was not run or extrapolating past the delta
    actually tested, and the batch's own ``status`` per row (exact / bound /
    infeasible / never ran) is part of the grounding.

    Not streamed and cached on the execution: the answer is a few sentences, and
    a reload must never re-bill a call. Same guardrails as the rest of the
    assistant — BYOK-first, monthly-budget pause, org rate limit. No moderation
    pre-check: the prompt is assembled from computed figures, not user text.

    ``use_advanced_model`` re-reads the same scenarios with the advanced model.
    The cache is keyed by the model that wrote the text, so asking for the other
    tier regenerates (and bills) while asking again for the same one does not.
    """
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == org.id,
        )
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    job = execution.scenario_analysis or {}
    analysis = job.get("result") if job.get("status") == scenario_job.STATUS_COMPLETED else None
    if not analysis or not analysis.get("computed"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Run the what-if analysis first — there is nothing to explain yet.",
        )

    use_advanced = bool(body.use_advanced_model) if body else False
    # Sonnet-tier by default: narrating computed figures needs no reasoning tier.
    model, _ = select_model(use_advanced=use_advanced, db=db)

    # The cache key is (model, language): the SAME scenarios read by another tier
    # or in another language are a different answer, and serving the stored one
    # would hand a Catalan reader the German text. Compared STRICTLY — a text
    # stored before we tracked these (no key) is regenerated once rather than
    # assumed to match, which is the assumption that produced exactly that bug.
    same_tier = job.get("explained_with") == model
    same_language = job.get("explained_locale") == locale
    if job.get("explanation") and same_tier and same_language:
        return ScenarioExplanationResponse(explanation=job["explanation"], cached=True)

    byok_client, is_byok = resolve_anthropic_client(org)

    if not is_byok and is_llm_budget_exceeded(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_not_available",
                "message": (
                    "The AI assistant is taking a short break — the platform's monthly "
                    "AI budget has been reached. It will be back at the start of next month."
                ),
                "reason": "llm_monthly_budget_exhausted",
            },
        )

    allowed, rate_info = check_rate_limit(
        f"llm:{org.id}",
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_MINUTE"),
        PSS.get_int(db, "LLM_RATE_LIMIT_PER_DAY"),
    )
    if not allowed:
        retry_after = rate_info.get("retry_after") if isinstance(rate_info, dict) else None
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        raise HTTPException(status_code=429, detail=rate_info, headers=headers)

    try:
        client = byok_client or get_anthropic_client(db=db)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "feature_not_available",
                "message": "The AI assistant is not configured on this instance.",
                "reason": "llm_not_configured",
            },
        ) from None

    request_id = getattr(request.state, "request_id", None) or ""
    try:
        outcome = await explain_scenarios(
            client=client,
            model=model,
            max_tokens=PSS.get_int(db, "LLM_MAX_TOKENS"),
            analysis=analysis,
            formulation=execution.input_data if isinstance(execution.input_data, dict) else None,
            locale=locale,
        )
    except Exception as exc:
        handle_anthropic_failure(
            exc, logger=logger, context="scenario explanation", request_id=request_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "ai_error",
                "message": "The AI service could not complete the request. Please try again.",
                "reason": "upstream_error",
            },
        ) from None

    if not outcome.text:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "ai_error",
                "message": "The AI service returned an empty explanation. Please try again.",
                "reason": "empty_reply",
            },
        )

    # Cache on the execution so a reload is free. Re-read under a lock: the batch
    # may have been re-run while the model was writing, and the envelope we hold
    # would otherwise overwrite the newer one.
    locked = (
        db.query(ModelExecution)
        .filter(ModelExecution.id == execution_id, ModelExecution.organization_id == org.id)
        .with_for_update(of=ModelExecution)
        .first()
    )
    if locked is not None:
        locked.scenario_analysis = {
            **(locked.scenario_analysis or job),
            "explanation": outcome.text,
            "explained_at": utcnow().isoformat(),
            "explained_with": model,
            "explained_locale": locale,
        }
    db.commit()

    if not is_byok:
        record_standalone_llm_spend(
            db,
            org_id=org.id,
            user_id=user.id,
            model=model,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            summary="What-if analysis explanation",
        )

    return ScenarioExplanationResponse(explanation=outcome.text, cached=False)
