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
from sqlalchemy.orm import Session, joinedload
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.models.conversation_attachment import ConversationAttachment
from app.models.llm_conversation import LLMConversation, LLMMessage
from app.schemas.attachment import AttachmentResponse
from app.schemas.llm import (
    ChatMessageRequest,
)
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.services.document_extraction import MAX_FILE_SIZE, extract_text
from app.services.llm import (
    generate_formulation_resilient,
    generate_text_response,
    moderate_message,
    select_model,
)
from app.services.llm.cost_tracking import (
    compute_message_cost_eur,
    is_llm_budget_exceeded,
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

    if conv.expires_at < utcnow().replace(tzinfo=None):
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

    Optionally initializes with a template formulation as the first assistant message.
    Requires the ``llm_assistant`` feature in the organization's plan.
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

    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=org.id,
        user_id=user.id,
        template_id=body.template_id,
        model_id=body.model_id,
        created_at=utcnow().replace(tzinfo=None),
        expires_at=(
            utcnow() + timedelta(hours=PSS.get_int(db, "LLM_CONVERSATION_TTL_HOURS"))
        ).replace(tzinfo=None),
    )

    # If template_id is provided, load template formulation as the first assistant message
    if body.template_id:
        template_formulation = _load_template_formulation(db, body.template_id)
        if template_formulation:
            msg = LLMMessage(
                id=generate_id("msg_"),
                conversation_id=conv.id,
                role="assistant",
                content=json.dumps(template_formulation),
                formulation_json=template_formulation,
                created_at=utcnow().replace(tzinfo=None),
            )
            conv.messages.append(msg)
            conv.current_formulation = template_formulation

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
) -> dict[str, Any]:
    """List active (non-expired) conversations for the current user."""
    now = utcnow().replace(tzinfo=None)
    query = (
        db.query(LLMConversation)
        .filter(
            LLMConversation.organization_id == org.id,
            LLMConversation.user_id == user.id,
            LLMConversation.expires_at > now,
        )
        .order_by(LLMConversation.created_at.desc())
    )

    if model_id:
        query = query.filter(LLMConversation.model_id == model_id)

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
    return None


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    request: Request,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
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

    # W17 budget guardrail: pause the assistant gracefully when the
    # platform's monthly Anthropic budget (LLM_MONTHLY_BUDGET_EUR) is
    # exhausted. Same friendly feature-disabled shape as the plan feature
    # gate in create_conversation so the UI degrades identically. The check
    # is cached in-process (~60s) — no per-message SUM aggregation.
    if is_llm_budget_exceeded(db):
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

    # Pre-pay LLM credits before streaming (refunded on failure)
    llm_credit_cost = PSS.get_int(db, "LLM_CREDIT_COST_PER_MESSAGE")
    llm_message_id = generate_id("msg_")  # Idempotency key for this LLM charge
    try:
        CreditsService.deduct_credits(
            db=db,
            organization_id=org.id,
            credits=llm_credit_cost,
            description=f"LLM message: {llm_message_id}",
            reference_type="llm_message",
            reference_id=llm_message_id,
        )
        db.commit()
    except InsufficientCreditsError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "insufficient_credits",
                "credits_needed": e.credits_needed,
                "credits_available": e.credits_available,
            },
        ) from None

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
        created_at=utcnow().replace(tzinfo=None),
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
    system_prompt = build_system_prompt(document_context, rag_context=rag_context)

    # Select model
    model, use_thinking = select_model(body.use_advanced_model, db=db)

    # Choose generator based on response_type
    is_explanation = body.response_type == "explanation"

    # Request id is set by RequestIdMiddleware and echoed back to clients
    # in every status/error SSE event so support can correlate chat-side
    # complaints with server logs and Prometheus metrics.
    request_id = getattr(request.state, "request_id", None) or ""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        """Async generator yielding SSE events."""
        accumulated_text = ""
        formulation_data = None
        stream_failed = False  # Track whether we saw a non-recoverable error event
        # W17: real token usage accumulated across ALL API calls this message
        # triggered (retries and chunked-generation calls each bill separately).
        total_input_tokens = 0
        total_output_tokens = 0

        # Select the appropriate generator
        if is_explanation:
            stream_gen = generate_text_response(
                api_messages, model, use_thinking, system_prompt=system_prompt, db=db
            )
        else:
            stream_gen = generate_formulation_resilient(
                api_messages,
                model,
                use_thinking,
                user_message=body.message,
                system_prompt=system_prompt,
                db=db,
            )

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
                    # If we saw an upstream error event, refund credits BEFORE
                    # emitting done. The done event always fires after error
                    # because generate_formulation yields {"type": "done"}
                    # unconditionally even on failure.
                    LLM_REQUESTS_TOTAL.labels(outcome="error" if stream_failed else "success").inc()
                    if stream_failed:
                        try:
                            credits_svc = CreditsService(db)
                            credits_svc.refund_credits(
                                organization_id=org.id,
                                credits=llm_credit_cost,
                                description=f"LLM stream failed, refunding: {llm_message_id}",
                                reference_type="llm_message_refund",
                                reference_id=llm_message_id,
                            )
                            db.commit()
                        except Exception as refund_err:
                            logger.error("Failed to refund credits: %s", refund_err)
                    else:
                        # Persist assistant message after stream completes
                        try:
                            # W17: price the real token usage via the
                            # per-model pricing map (platform setting).
                            # NULL columns mean "usage was never captured"
                            # (pre-migration rows / providers without usage),
                            # not "zero tokens".
                            has_usage = bool(total_input_tokens or total_output_tokens)
                            message_cost = (
                                compute_message_cost_eur(
                                    db, model, total_input_tokens, total_output_tokens
                                )
                                if has_usage
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
                                created_at=utcnow().replace(tzinfo=None),
                            )
                            db.add(assistant_msg)

                            # Update conversation's current formulation
                            # (only for formulation responses, not explanations)
                            if formulation_data and not is_explanation:
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
            # Refund pre-paid credits on stream failure
            try:
                credits_svc = CreditsService(db)
                credits_svc.refund_credits(
                    organization_id=org.id,
                    credits=llm_credit_cost,
                    description=f"LLM stream failed, refunding: {llm_message_id}",
                    reference_type="llm_message_refund",
                    reference_id=llm_message_id,
                )
                db.commit()
            except Exception as refund_err:
                logger.error("Failed to refund credits: %s", refund_err)
            yield {
                "event": "error",
                "data": json.dumps({"code": code.value, "request_id": request_id}),
            }

    return EventSourceResponse(event_generator())


# Extension-to-MIME mapping for allowed document types
_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".txt": "text/plain",
}


@router.post("/conversations/{conversation_id}/attachments")
async def upload_attachment(
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
    content = await file.read()
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
    return None


def _load_template_formulation(db: Session, template_id: str) -> dict[str, Any] | None:
    """Load a template formulation from the model catalog.

    Returns the formulation dict or None if template not found.
    """
    from app.models.optimization_model import ModelCatalog

    template = db.query(ModelCatalog).filter(ModelCatalog.id == template_id).first()
    if not template:
        return None

    # If the template has a default_formulation JSON field, use it.
    # Otherwise return None — the template exists but has no pre-built formulation.
    return getattr(template, "default_formulation", None)
