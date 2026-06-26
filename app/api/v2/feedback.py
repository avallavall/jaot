"""User-facing feedback endpoints: LLM formulation rating."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.models.formulation_rating import FormulationRating
from app.models.llm_conversation import LLMConversation
from app.schemas.feedback import (
    RatingCreate,
    RatingResponse,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post(
    "/conversations/{conversation_id}/rating",
    response_model=RatingResponse,
    status_code=status.HTTP_200_OK,
)
def rate_conversation(
    conversation_id: str,
    body: RatingCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> Any:
    """Create or update (UPSERT) a rating for a conversation.

    Re-rating the same conversation overwrites the previous rating.
    """
    # Verify conversation exists and belongs to the user
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

    now = utcnow().replace(tzinfo=None)
    if conv.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation has expired",
        )

    # UPSERT: check existing rating
    existing = (
        db.query(FormulationRating)
        .filter(
            FormulationRating.conversation_id == conversation_id,
            FormulationRating.user_id == user.id,
        )
        .first()
    )

    if existing:
        existing.rating = body.rating
        existing.comment = body.comment
        existing.zone = body.zone
        existing.formulation_snapshot = body.formulation_snapshot
        existing.updated_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    new_rating = FormulationRating(
        id=generate_id("frt_"),
        conversation_id=conversation_id,
        user_id=user.id,
        organization_id=org.id,
        rating=body.rating,
        comment=body.comment,
        zone=body.zone,
        formulation_snapshot=body.formulation_snapshot,
    )
    db.add(new_rating)
    db.commit()
    db.refresh(new_rating)
    return new_rating


@router.get(
    "/conversations/{conversation_id}/rating",
    response_model=RatingResponse,
)
def get_conversation_rating(
    conversation_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> Any:
    """Get the authenticated user's rating for a conversation."""
    rating = (
        db.query(FormulationRating)
        .filter(
            FormulationRating.conversation_id == conversation_id,
            FormulationRating.user_id == user.id,
            FormulationRating.organization_id == org.id,
        )
        .first()
    )

    if not rating:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rating not found",
        )

    return rating
