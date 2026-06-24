"""Prometheus collector for the LLM monthly cost + budget gauges (W17).

Exposes on the existing /metrics endpoint:

- ``jaot_llm_cost_eur_month`` — SUM(llm_messages.cost_eur) for the current
  calendar month (real Anthropic spend, EUR).
- ``jaot_llm_budget_eur``     — the LLM_MONTHLY_BUDGET_EUR platform setting.

A custom collector (instead of a plain Gauge) computes values at scrape
time. The underlying read goes through
``app.services.llm.cost_tracking.get_budget_status`` which caches the
(cost, budget) pair in-process for ~60s, so Prometheus' 15s scrape interval
never hammers the DB with SUM() aggregations.

The collector NEVER raises — an exception inside ``collect()`` breaks the
entire /metrics response for every other metric. On a read failure it
serves the last-known values (or omits the gauges entirely before the
first successful read).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)


class LLMBudgetCollector:
    """Scrape-time collector for jaot_llm_cost_eur_month / jaot_llm_budget_eur."""

    def __init__(self) -> None:
        # Stale-if-error fallback so a transient DB blip during a scrape
        # does not blank the series (which would defuse the budget alerts).
        self._last: tuple[float, float] | None = None

    def collect(self) -> Iterator[GaugeMetricFamily]:
        status = self._read_status()
        if status is None:
            return
        cost, budget = status

        cost_gauge = GaugeMetricFamily(
            "jaot_llm_cost_eur_month",
            "Real Anthropic spend (EUR) for the current calendar month, "
            "summed from llm_messages.cost_eur (W17; ~60s cache).",
        )
        cost_gauge.add_metric([], cost)
        yield cost_gauge

        budget_gauge = GaugeMetricFamily(
            "jaot_llm_budget_eur",
            "Monthly Anthropic budget (EUR) from the LLM_MONTHLY_BUDGET_EUR "
            "platform setting (0 = guardrail disabled).",
        )
        budget_gauge.add_metric([], budget)
        yield budget_gauge

    def _read_status(self) -> tuple[float, float] | None:
        try:
            # Local imports: keep this module importable without the app's
            # DB/service stack (mirrors errors.py's lazy-metric pattern) and
            # avoid app.shared -> app.services import cycles at module load.
            from app.services.llm.cost_tracking import get_budget_status
            from app.shared.db.session import SessionLocal

            db = SessionLocal()
            try:
                status = get_budget_status(db)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("LLM budget collector read failed: %s", exc)
            return self._last
        self._last = status
        return status


_registered = False


def register_llm_budget_collector() -> None:
    """Register the collector on the default registry, idempotently.

    ``create_app()`` runs many times in the test suite — a duplicate
    registration raises ValueError, so guard with a module flag and treat
    the duplicate error as already-done.
    """
    global _registered
    if _registered:
        return
    try:
        REGISTRY.register(LLMBudgetCollector())
        _registered = True
    except ValueError:
        # Duplicated timeseries — another instance already registered.
        _registered = True


__all__ = ["LLMBudgetCollector", "register_llm_budget_collector"]
