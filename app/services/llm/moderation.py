"""Content moderation for LLM formulation chat.

Lightweight pre-filter that catches obviously off-topic or offensive prompts
before they reach the LLM. The system prompt handles nuanced cases.
"""

import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Rejection message for off-topic content
_OFFTOPIC_REJECTION = (
    "I can only help with optimization problems. Could you describe a problem "
    "involving decisions, constraints, and an objective to optimize?"
)

# Rejection message for offensive content
_OFFENSIVE_REJECTION = (
    "I'm not able to process that message. Please describe an optimization "
    "problem you'd like help formulating."
)

# Patterns that clearly indicate non-optimization requests
_OFFTOPIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(write|compose|create)\b.*\b(poem|song|story|essay|letter|novel)\b", re.IGNORECASE
    ),
    re.compile(r"\b(hack|crack|break)\s+(into|password|account|server|database)\b", re.IGNORECASE),
    re.compile(r"\bbypass\b.{0,20}\b(security|auth|firewall|password|login)\b", re.IGNORECASE),
    re.compile(r"\b(recipe|cook|bake|ingredients)\b.*\b(for|to make)\b", re.IGNORECASE),
    re.compile(r"\btell me a joke\b", re.IGNORECASE),
    re.compile(r"\b(translate|translation)\b.*\b(to|into|from)\b", re.IGNORECASE),
    re.compile(
        r"\b(code|program|script)\b.*\b(in|using)\b\s*(python|java|c\+\+|rust|go)\b", re.IGNORECASE
    ),
    re.compile(r"\bplay a game\b", re.IGNORECASE),
    re.compile(r"\b(horoscope|zodiac|astrology)\b", re.IGNORECASE),
]

# Offensive language patterns (basic profanity filter)
_OFFENSIVE_WORDS: set[str] = {
    "fuck",
    "shit",
    "damn",
    "bitch",
    "asshole",
    "bastard",
    "dick",
    "cunt",
    "nigger",
    "faggot",
    "retard",
}


def moderate_message(message: str) -> tuple[bool, str | None]:
    """Check if a message is appropriate for the optimization assistant.

    This is a fast pre-filter. Claude's system prompt handles edge cases.

    Args:
        message: The user's message text.

    Returns:
        Tuple of (is_allowed, rejection_message).
        If allowed, rejection_message is None.
    """
    # Normalize for checking
    lower = message.lower().strip()

    words = set(re.findall(r"\b\w+\b", lower))
    if words & _OFFENSIVE_WORDS:
        logger.warning("Offensive content detected in message")
        return False, _OFFENSIVE_REJECTION

    # Optimization-context keywords — if present, skip off-topic check
    # (prevents false positives on food/bakery/manufacturing optimization)
    _OPT_KEYWORDS = {
        "optim",
        "minimiz",
        "maximiz",
        "cost",
        "profit",
        "constraint",
        "variable",
        "allocat",
        "schedule",
        "plan",
        "linear",
        "integer",
        "binary",
        "objective",
        "feasib",
        "solver",
        "production",
        "assign",
        "warehouse",
        "transport",
        "logistics",
        "supply chain",
        "routing",
        "capacit",
        "demand",
        "inventory",
        "resource",
        "efficien",
        "formul",
        "model",
        "decision",
        "network",
        "structur",
    }
    has_opt_context = any(kw in lower for kw in _OPT_KEYWORDS)

    for pattern in _OFFTOPIC_PATTERNS:
        if pattern.search(message):
            # If the message also contains optimization keywords, allow it
            if has_opt_context:
                logger.info("Off-topic pattern found but optimization context present, allowing")
                continue
            logger.info("Off-topic message detected: %s", pattern.pattern[:50])
            return False, _OFFTOPIC_REJECTION

    # Message is allowed
    return True, None


async def report_flagged_message(
    db: Session,
    user_id: str,
    organization_id: str,
    message: str,
    reason: str,
) -> None:
    """Report a flagged message for admin review.

    Creates a notification entry for admin review using the existing
    notification pattern.

    Args:
        db: Database session.
        user_id: ID of the user who sent the message.
        organization_id: Organization ID.
        message: The flagged message content (truncated for storage).
        reason: Why it was flagged.
    """
    from app.models.notification import Notification, NotificationType
    from app.shared.utils.datetime_helpers import utcnow
    from app.shared.utils.id_generator import generate_id

    try:
        notification = Notification(
            id=generate_id("ntf_"),
            organization_id=organization_id,
            user_id=user_id,
            type=NotificationType.SYSTEM,
            title="Flagged LLM message",
            message=f"Reason: {reason}. Content: {message[:200]}",
            created_at=utcnow(),
        )
        db.add(notification)
        db.flush()
        logger.info(
            "Flagged message reported: user=%s org=%s reason=%s",
            user_id,
            organization_id,
            reason,
        )
    except Exception as e:
        logger.error("Failed to report flagged message: %s", e)
        raise
