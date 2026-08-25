"""Real LLM cost tracking + monthly budget guardrail (W17).

Token usage is captured from Anthropic responses (streaming: the
``message_start`` event carries ``input_tokens``, the final ``message_delta``
carries cumulative ``output_tokens``; non-streaming: ``response.usage``) and
persisted on ``llm_messages`` (``input_tokens``, ``output_tokens``,
``cost_eur``). Cost is computed from the ``LLM_MODEL_PRICING_EUR_PER_MTOK``
platform setting (category llm) — a JSON map of model id ->
``{"input": eur_per_mtok, "output": eur_per_mtok}`` with a ``"default"``
entry for unknown models.

The monthly budget guardrail (``LLM_MONTHLY_BUDGET_EUR``, default 20 EUR,
0 disables) pauses the assistant gracefully when the calendar-month spend
reaches the budget. Both values feed the Prometheus gauges
``jaot_llm_cost_eur_month`` / ``jaot_llm_budget_eur``
(app/shared/core/llm_budget_metrics.py) so Alertmanager can warn at >80%
and page at >=100%.

The (cost, budget) pair is cached in-process for ~60s so neither the
per-message budget gate nor the Prometheus scrape (15s interval) hammers
the DB with SUM() aggregations.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.llm_conversation import LLMConversation, LLMMessage
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.ttl_probe import TTLProbe

logger = logging.getLogger(__name__)

PRICING_SETTING_KEY = "LLM_MODEL_PRICING_EUR_PER_MTOK"
BUDGET_SETTING_KEY = "LLM_MONTHLY_BUDGET_EUR"

# Standalone (non-conversational) LLM features — B3 "generate JModel with AI" today —
# still spend against the shared Anthropic key, so their cost MUST count toward the
# monthly budget (get_month_cost_eur sums every llm_messages.cost_eur). They have no
# user-facing conversation, so we book the spend into a hidden per-(org,user)
# bookkeeping conversation tagged with this sentinel model_id, which list_conversations
# filters out (the "sys:" prefix).
LEDGER_MODEL_ID_PREFIX = "sys:"
_JMODEL_AI_LEDGER_MODEL_ID = "sys:jmodel-ai"

# Hard-coded last-resort rate if the pricing setting is missing or
# unparseable: Opus-tier pricing, so failures over-estimate cost and the
# guardrail errs toward pausing too early — never toward silent overspend.
_FALLBACK_RATE: dict[str, float] = {"input": 4.63, "output": 23.15}

#: ``wait``: the refresh is one SUM over the current month plus one settings
#: read, both short and bounded, so a caller that finds one running is better
#: off waiting than running its own. Before this it had no single flight at
#: all: N callers arriving on an expired cache each ran the month-cost query.
_budget_probe = TTLProbe[tuple[float, float]](ttl_seconds=60.0, on_contention="wait")


def get_model_pricing(db: Session) -> dict[str, dict[str, float]]:
    """Parse the per-model pricing map setting; degrade to the fallback rate."""
    try:
        raw = PSS.get_str(db, PRICING_SETTING_KEY)
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed:
            return parsed
    except Exception as exc:
        logger.warning("Unparseable %s setting: %s", PRICING_SETTING_KEY, exc)
    return {"default": dict(_FALLBACK_RATE)}


def compute_message_cost_eur(
    db: Session,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """EUR cost of one API exchange from real token counts.

    Unknown models fall back to the map's ``"default"`` entry, then to the
    hard-coded Opus-tier rate — cost is never silently zero for a model
    missing from the map.
    """
    pricing = get_model_pricing(db)
    entry = pricing.get(model) or pricing.get("default") or _FALLBACK_RATE
    if not isinstance(entry, dict):
        entry = _FALLBACK_RATE
    in_rate = float(entry.get("input", _FALLBACK_RATE["input"]))
    out_rate = float(entry.get("output", _FALLBACK_RATE["output"]))
    cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
    return round(cost, 6)


def get_month_cost_eur(db: Session) -> float:
    """SUM(llm_messages.cost_eur) for the current calendar month (UTC)."""
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(LLMMessage.cost_eur), 0))
        .filter(LLMMessage.created_at >= month_start)
        .scalar()
    )
    return float(total or 0)


def get_budget_status(db: Session) -> tuple[float, float]:
    """Return ``(month_cost_eur, budget_eur)``, cached in-process for ~60s."""
    return _budget_probe.get(
        lambda: (get_month_cost_eur(db), PSS.get_float(db, BUDGET_SETTING_KEY))
    )


def is_llm_budget_exceeded(db: Session) -> bool:
    """True when the calendar-month spend has reached the configured budget.

    A budget of 0 (or negative) disables the guardrail entirely — the
    documented admin escape hatch.
    """
    cost, budget = get_budget_status(db)
    if budget <= 0:
        return False
    return cost >= budget


def reset_budget_cache() -> None:
    """Drop the cached (cost, budget) pair. Tests + admin settings updates."""
    _budget_probe.clear()


def _ledger_conversation(db: Session, org_id: str, user_id: str) -> LLMConversation | None:
    """The (org, user) hidden JModel-AI cost-ledger conversation, if it exists."""
    return (
        db.query(LLMConversation)
        .filter(
            LLMConversation.organization_id == org_id,
            LLMConversation.user_id == user_id,
            LLMConversation.model_id == _JMODEL_AI_LEDGER_MODEL_ID,
        )
        .first()
    )


def record_standalone_llm_spend(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    summary: str,
) -> None:
    """Book token usage + EUR cost for an LLM call with no user-facing conversation.

    Ensures a hidden per-(org, user) bookkeeping conversation exists and appends a
    ``system``-role message carrying the real token counts and priced cost, so the
    monthly-budget SUM includes this spend. Call ONLY for platform-key (billable)
    spend — BYOK runs on the org's own account and must never touch the platform
    budget. Best-effort: a bookkeeping failure never propagates to the caller (the
    user's generation already succeeded); it is logged and rolled back.
    """
    if not (input_tokens or output_tokens):
        return
    try:
        conv = _ledger_conversation(db, org_id, user_id)
        if conv is None:
            conv = LLMConversation(
                id=generate_id("conv_"),
                organization_id=org_id,
                user_id=user_id,
                model_id=_JMODEL_AI_LEDGER_MODEL_ID,
                created_at=utcnow(),
                # Far-future expiry: this row is a durable cost ledger, not an
                # ephemeral chat, so it must survive any future TTL purge.
                expires_at=utcnow() + timedelta(days=3650),
            )
            db.add(conv)
            try:
                db.flush()
            except IntegrityError:
                # Lost the get-or-create race (uq_llm_conversations_sys_ledger):
                # a concurrent spend created the ledger first — roll back our
                # create (the session holds nothing else at this point in the
                # generate flow) and adopt the winner's row.
                db.rollback()
                conv = _ledger_conversation(db, org_id, user_id)
                if conv is None:
                    raise

        cost = compute_message_cost_eur(db, model, input_tokens, output_tokens)
        db.add(
            LLMMessage(
                id=generate_id("msg_"),
                conversation_id=conv.id,
                role="system",
                content=summary,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_eur=cost,
                created_at=utcnow(),
            )
        )
        db.commit()
    except Exception:
        logger.warning("Failed to record standalone LLM spend", exc_info=True)
        db.rollback()


__all__ = [
    "BUDGET_SETTING_KEY",
    "LEDGER_MODEL_ID_PREFIX",
    "PRICING_SETTING_KEY",
    "compute_message_cost_eur",
    "get_budget_status",
    "get_model_pricing",
    "get_month_cost_eur",
    "is_llm_budget_exceeded",
    "record_standalone_llm_spend",
    "reset_budget_cache",
]
