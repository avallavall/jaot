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
import threading
import time

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.llm_conversation import LLMMessage
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

PRICING_SETTING_KEY = "LLM_MODEL_PRICING_EUR_PER_MTOK"
BUDGET_SETTING_KEY = "LLM_MONTHLY_BUDGET_EUR"

# Hard-coded last-resort rate if the pricing setting is missing or
# unparseable: Opus-tier pricing, so failures over-estimate cost and the
# guardrail errs toward pausing too early — never toward silent overspend.
_FALLBACK_RATE: dict[str, float] = {"input": 4.63, "output": 23.15}

_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cached_at: float = 0.0
_cached_status: tuple[float, float] | None = None


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
    now = utcnow().replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        db.query(func.coalesce(func.sum(LLMMessage.cost_eur), 0))
        .filter(LLMMessage.created_at >= month_start)
        .scalar()
    )
    return float(total or 0)


def get_budget_status(db: Session) -> tuple[float, float]:
    """Return ``(month_cost_eur, budget_eur)``, cached in-process for ~60s."""
    global _cached_at, _cached_status
    with _cache_lock:
        if _cached_status is not None and (time.monotonic() - _cached_at) < _CACHE_TTL_SECONDS:
            return _cached_status

    cost = get_month_cost_eur(db)
    budget = PSS.get_float(db, BUDGET_SETTING_KEY)

    with _cache_lock:
        _cached_status = (cost, budget)
        _cached_at = time.monotonic()
    return cost, budget


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
    global _cached_at, _cached_status
    with _cache_lock:
        _cached_status = None
        _cached_at = 0.0


__all__ = [
    "BUDGET_SETTING_KEY",
    "PRICING_SETTING_KEY",
    "compute_message_cost_eur",
    "get_budget_status",
    "get_model_pricing",
    "get_month_cost_eur",
    "is_llm_budget_exceeded",
    "reset_budget_cache",
]
