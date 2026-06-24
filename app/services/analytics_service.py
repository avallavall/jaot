"""Central analytics service for feature usage tracking.

Provides fire-and-forget event logging via log_event() and aggregation
queries for the admin analytics dashboard.
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analytics_event import AnalyticsEvent
from app.schemas.analytics import (
    ConversionFunnelResponse,
    ConversionFunnelStep,
    CountryDistributionEntry,
    DomainSummaryEntry,
    EventBreakdownEntry,
    FeatureAnalyticsKPI,
    FeatureAnalyticsOverview,
    FeatureTimeSeriesPoint,
    FeatureTimeSeriesResponse,
    GroupedTimeSeriesPoint,
    GroupedTimeSeriesResponse,
    PaginatedRecentEventsResponse,
    RecentEventEntry,
)
from app.services.seller_analytics_service import _get_geoip_country
from app.shared.constants.event_types import ALL_EVENT_TYPES, EVENT_DOMAINS, FUNNEL_STEPS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Funnel step fill colors (blue -> indigo -> violet -> green)
_FUNNEL_FILLS = ["#3b82f6", "#6366f1", "#8b5cf6", "#22c55e"]


def _analytics_period_since(period: str) -> datetime | None:
    """Convert a period string to a since-datetime.

    Extends the seller analytics _period_since with short intervals:
    1h, 12h, today, 7d, 30d, 90d. Returns None for 'all'.
    """
    now = utcnow()
    if period == "1h":
        return now - timedelta(hours=1)
    if period == "12h":
        return now - timedelta(hours=12)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    days = mapping.get(period)
    if days is not None:
        return now - timedelta(days=days)
    return None  # "all" -- no filter


def _comparison_period_since(
    period: str,
) -> tuple[datetime | None, datetime | None]:
    """Return (prev_since, prev_until) for the prior period of equal length.

    Used for period-over-period comparison. Returns (None, None) for "all".
    """
    now = utcnow()
    if period == "1h":
        return (now - timedelta(hours=2), now - timedelta(hours=1))
    if period == "12h":
        return (now - timedelta(hours=24), now - timedelta(hours=12))
    if period == "today":
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_midnight = today_midnight - timedelta(days=1)
        return (yesterday_midnight, today_midnight)
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    days = mapping.get(period)
    if days is not None:
        return (
            now - timedelta(days=days * 2),
            now - timedelta(days=days),
        )
    return (None, None)  # "all" -- no comparison possible


class AnalyticsService:
    """Central analytics service with fire-and-forget logging and aggregation queries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def log_event(
        self,
        user_id: str,
        org_id: str,
        event_type: str,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Create an analytics event record.

        Called fire-and-forget from endpoint handlers. Uses geoIP for
        country_code lookup from the request IP.
        """
        country = _get_geoip_country(ip_address)
        event = AnalyticsEvent(
            id=generate_id("ae_"),
            user_id=user_id,
            org_id=org_id,
            event_type=event_type,
            country_code=country,
            event_metadata=metadata,
            created_at=utcnow(),
        )
        self.db.add(event)
        self.db.commit()

    def _base_query(  # noqa: ANN202
        self,
        since: datetime | None,
        *,
        until: datetime | None = None,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
    ):
        """Build base query with optional time and dimension filters."""
        q = self.db.query(AnalyticsEvent)
        if since is not None:
            q = q.filter(AnalyticsEvent.created_at >= since)
        if until is not None:
            q = q.filter(AnalyticsEvent.created_at < until)
        if domain is not None:
            domain_types = EVENT_DOMAINS.get(domain, [])
            if domain_types:
                q = q.filter(AnalyticsEvent.event_type.in_(domain_types))
        if event_type is not None:
            q = q.filter(AnalyticsEvent.event_type == event_type)
        if country_code is not None:
            q = q.filter(AnalyticsEvent.country_code == country_code)
        return q

    def get_event_counts(
        self,
        period: str,
        *,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
        compare: bool = False,
    ) -> FeatureAnalyticsKPI:
        """Aggregate event counts for KPI cards.

        Returns total events, active users, events today, and top
        event type. Optionally includes previous-period values.
        """
        since = _analytics_period_since(period)
        filters = dict(
            event_type=event_type,
            country_code=country_code,
            domain=domain,
        )

        # Total events and active users in period
        stats = (
            self._base_query(since, **filters)
            .with_entities(
                func.count().label("total"),
                func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
            )
            .first()
        )
        total_events = stats.total if stats else 0  # type: ignore[union-attr]
        active_users = stats.users if stats else 0  # type: ignore[union-attr]

        # Events today
        today_since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        events_today = self._base_query(today_since, **filters).count()

        # Top event type in period
        top_row = (
            self._base_query(since, **filters)
            .with_entities(
                AnalyticsEvent.event_type,
                func.count().label("cnt"),
            )
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count().desc())
            .first()
        )
        top_event_type = (
            top_row.event_type if top_row else None  # type: ignore[union-attr]
        )
        top_event_count = (
            top_row.cnt if top_row else 0  # type: ignore[union-attr]
        )

        # Previous-period comparison
        prev_total: int | None = None
        prev_users: int | None = None
        prev_today: int | None = None
        if compare:
            prev_since, prev_until = _comparison_period_since(period)
            if prev_since is not None:
                prev_stats = (
                    self._base_query(prev_since, until=prev_until, **filters)
                    .with_entities(
                        func.count().label("total"),
                        func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
                    )
                    .first()
                )
                prev_total = (
                    prev_stats.total if prev_stats else 0  # type: ignore[union-attr]
                )
                prev_users = (
                    prev_stats.users if prev_stats else 0  # type: ignore[union-attr]
                )
                yesterday_start = today_since - timedelta(days=1)
                prev_today = self._base_query(
                    yesterday_start,
                    until=today_since,
                    **filters,
                ).count()

        return FeatureAnalyticsKPI(
            total_events=total_events,
            active_users=active_users,
            events_today=events_today,
            top_event_type=top_event_type,
            top_event_count=top_event_count,
            period=period,
            prev_total_events=prev_total,
            prev_active_users=prev_users,
            prev_events_today=prev_today,
        )

    def get_time_series(
        self,
        period: str,
        event_type: str | None = None,
        *,
        country_code: str | None = None,
        domain: str | None = None,
        group_by: Literal["domain", "event_type"] | None = None,
    ) -> FeatureTimeSeriesResponse | GroupedTimeSeriesResponse:
        """Time series of event counts.

        Uses hourly granularity for periods <= "today", daily for
        longer. When group_by is "domain" or "event_type", returns
        a GroupedTimeSeriesResponse with per-series counts.
        """
        since = _analytics_period_since(period)
        short_periods = {"1h", "12h", "today"}
        trunc_unit = "hour" if period in short_periods else "day"
        filters = dict(
            event_type=event_type,
            country_code=country_code,
            domain=domain,
        )
        bucket_col = func.date_trunc(trunc_unit, AnalyticsEvent.created_at)

        if group_by in ("domain", "event_type"):
            q = self._base_query(since, **filters)
            rows = (
                q.with_entities(
                    bucket_col.label("bucket"),
                    AnalyticsEvent.event_type,
                    func.count().label("cnt"),
                )
                .group_by(bucket_col, AnalyticsEvent.event_type)
                .order_by(bucket_col)
                .all()
            )
            return self._pivot_grouped_series(rows, period, group_by)

        q = self._base_query(since, **filters)
        rows = (
            q.with_entities(
                bucket_col.label("bucket"),
                func.count().label("cnt"),
            )
            .group_by(bucket_col)
            .order_by(bucket_col)
            .all()
        )
        data = [
            FeatureTimeSeriesPoint(
                date=str(row.bucket),
                count=row.cnt,
                event_type=event_type,
            )
            for row in rows
        ]
        return FeatureTimeSeriesResponse(data=data, period=period)

    @staticmethod
    def _pivot_grouped_series(
        rows: list,
        period: str,
        group_by: Literal["domain", "event_type"],
    ) -> GroupedTimeSeriesResponse:
        """Pivot raw (bucket, event_type, cnt) rows.

        When group_by=="domain", aggregates event types into their
        domain names. Otherwise keeps individual event_type keys.
        """
        from collections import defaultdict

        buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        if group_by == "domain":
            type_to_domain: dict[str, str] = {}
            for dom, types in EVENT_DOMAINS.items():
                for t in types:
                    type_to_domain[t] = dom
            for row in rows:
                date_key = str(row.bucket)
                dom_name = type_to_domain.get(row.event_type, "Other")
                buckets[date_key][dom_name] += row.cnt
        else:
            for row in rows:
                date_key = str(row.bucket)
                buckets[date_key][row.event_type] += row.cnt

        data = [
            GroupedTimeSeriesPoint(date=date_key, series=dict(series))
            for date_key, series in sorted(buckets.items())
        ]
        return GroupedTimeSeriesResponse(data=data, period=period, group_by=group_by)

    def get_event_breakdown(
        self,
        period: str,
        *,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
        compare: bool = False,
    ) -> list[EventBreakdownEntry]:
        """Event counts per type, including all known types (0 count)."""
        since = _analytics_period_since(period)
        filters = dict(
            event_type=event_type,
            country_code=country_code,
            domain=domain,
        )
        rows = (
            self._base_query(since, **filters)
            .with_entities(
                AnalyticsEvent.event_type,
                func.count().label("cnt"),
            )
            .group_by(AnalyticsEvent.event_type)
            .all()
        )
        type_counts: dict[str, int] = {row.event_type: row.cnt for row in rows}

        # Previous-period counts
        prev_counts: dict[str, int] = {}
        if compare:
            prev_since, prev_until = _comparison_period_since(period)
            if prev_since is not None:
                prev_rows = (
                    self._base_query(prev_since, until=prev_until, **filters)
                    .with_entities(
                        AnalyticsEvent.event_type,
                        func.count().label("cnt"),
                    )
                    .group_by(AnalyticsEvent.event_type)
                    .all()
                )
                prev_counts = {r.event_type: r.cnt for r in prev_rows}

        # Include all known event types, even with 0 count
        result = []
        for et in ALL_EVENT_TYPES:
            entry = EventBreakdownEntry(
                event_type=et,
                count=type_counts.get(et, 0),
                prev_count=(prev_counts.get(et, 0) if compare else None),
            )
            result.append(entry)

        result.sort(key=lambda e: e.count, reverse=True)
        return result

    def get_domain_summary(
        self,
        period: str,
        *,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
        type_counts: dict[str, int] | None = None,
    ) -> list[DomainSummaryEntry]:
        """Aggregate counts per domain for radar chart.

        Uses EVENT_DOMAINS mapping to group event types into domains.
        Accepts pre-computed type_counts to avoid duplicate GROUP BY query
        when called from get_overview (which already has breakdown data).
        """
        if type_counts is None:
            since = _analytics_period_since(period)
            filters = dict(
                event_type=event_type,
                country_code=country_code,
                domain=domain,
            )
            rows = (
                self._base_query(since, **filters)
                .with_entities(
                    AnalyticsEvent.event_type,
                    func.count().label("cnt"),
                )
                .group_by(AnalyticsEvent.event_type)
                .all()
            )
            type_counts = {row.event_type: row.cnt for row in rows}

        result = []
        for dom_name, dom_types in EVENT_DOMAINS.items():
            count = sum(type_counts.get(et, 0) for et in dom_types)
            result.append(DomainSummaryEntry(domain=dom_name, count=count))
        return result

    def get_conversion_funnel(
        self,
        period: str,
        *,
        country_code: str | None = None,
        compare: bool = False,
    ) -> ConversionFunnelResponse:
        """Conversion funnel: COUNT(DISTINCT user_id) per step.

        Steps: signup -> model create -> solve -> paid action.
        Uses a single GROUP BY query instead of per-step queries.
        """
        since = _analytics_period_since(period)

        # Single query for all funnel steps
        q = self._base_query(since, country_code=country_code).filter(
            AnalyticsEvent.event_type.in_(FUNNEL_STEPS)
        )
        rows = (
            q.with_entities(
                AnalyticsEvent.event_type,
                func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
            )
            .group_by(AnalyticsEvent.event_type)
            .all()
        )
        step_counts: dict[str, int] = {r.event_type: r.users for r in rows}

        # Previous-period comparison in a single query
        prev_counts: dict[str, int] = {}
        if compare:
            prev_since, prev_until = _comparison_period_since(period)
            if prev_since is not None:
                pq = self._base_query(
                    prev_since, until=prev_until, country_code=country_code
                ).filter(AnalyticsEvent.event_type.in_(FUNNEL_STEPS))
                prev_rows = (
                    pq.with_entities(
                        AnalyticsEvent.event_type,
                        func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
                    )
                    .group_by(AnalyticsEvent.event_type)
                    .all()
                )
                prev_counts = {r.event_type: r.users for r in prev_rows}

        steps: list[ConversionFunnelStep] = []
        for i, step_type in enumerate(FUNNEL_STEPS):
            fill = _FUNNEL_FILLS[i] if i < len(_FUNNEL_FILLS) else "#6b7280"
            steps.append(
                ConversionFunnelStep(
                    name=step_type,
                    value=step_counts.get(step_type, 0),
                    fill=fill,
                    prev_value=prev_counts.get(step_type, 0) if compare else None,
                )
            )

        return ConversionFunnelResponse(steps=steps)

    def get_country_distribution(
        self,
        period: str,
        limit: int = 15,
        *,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
    ) -> list[CountryDistributionEntry]:
        """Top countries by event count."""
        since = _analytics_period_since(period)
        filters = dict(
            event_type=event_type,
            country_code=country_code,
            domain=domain,
        )
        rows = (
            self._base_query(since, **filters)
            .filter(AnalyticsEvent.country_code.isnot(None))
            .with_entities(
                AnalyticsEvent.country_code,
                func.count().label("cnt"),
            )
            .group_by(AnalyticsEvent.country_code)
            .order_by(func.count().desc())
            .limit(limit)
            .all()
        )
        return [
            CountryDistributionEntry(country_code=row.country_code, count=row.cnt) for row in rows
        ]

    def get_recent_events(self, limit: int = 20) -> list[RecentEventEntry]:
        """Last N events ordered by created_at desc."""
        events = (
            self.db.query(AnalyticsEvent)
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            RecentEventEntry(
                id=e.id,
                event_type=e.event_type,
                user_id=e.user_id,
                country_code=e.country_code,
                created_at=str(e.created_at),
                metadata=e.event_metadata,
            )
            for e in events
        ]

    def get_recent_events_paginated(
        self,
        period: str,
        *,
        page: int = 1,
        page_size: int = 20,
        event_type: str | None = None,
        country_code: str | None = None,
    ) -> PaginatedRecentEventsResponse:
        """Paginated recent events with optional filters."""
        since = _analytics_period_since(period)
        filters = dict(event_type=event_type, country_code=country_code)
        base = self._base_query(since, **filters)

        total = base.count()
        offset = (page - 1) * page_size
        events = (
            base.order_by(AnalyticsEvent.created_at.desc()).offset(offset).limit(page_size).all()
        )
        items = [
            RecentEventEntry(
                id=e.id,
                event_type=e.event_type,
                user_id=e.user_id,
                country_code=e.country_code,
                created_at=str(e.created_at),
                metadata=e.event_metadata,
            )
            for e in events
        ]
        return PaginatedRecentEventsResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_overview(
        self,
        period: str,
        *,
        event_type: str | None = None,
        country_code: str | None = None,
        domain: str | None = None,
        compare: bool = False,
        ts_group: str | None = None,
    ) -> FeatureAnalyticsOverview:
        """Full analytics overview assembling all sections."""
        filters = dict(
            event_type=event_type,
            country_code=country_code,
            domain=domain,
        )
        breakdown = self.get_event_breakdown(period, compare=compare, **filters)
        type_counts = {e.event_type: e.count for e in breakdown}

        # Grouped time series (optional, for domain/event_type views)
        grouped_ts = None
        if ts_group in ("domain", "event_type"):
            grouped_resp = self.get_time_series(period, group_by=ts_group, **filters)
            if isinstance(grouped_resp, GroupedTimeSeriesResponse):
                grouped_ts = grouped_resp.data

        return FeatureAnalyticsOverview(
            kpi=self.get_event_counts(period, compare=compare, **filters),
            time_series=self.get_time_series(period, **filters),
            event_breakdown=breakdown,
            domain_summary=self.get_domain_summary(
                period,
                type_counts=type_counts,
                **filters,
            ),
            funnel=self.get_conversion_funnel(
                period,
                country_code=country_code,
                compare=compare,
            ),
            country_distribution=self.get_country_distribution(period, **filters),
            grouped_time_series=grouped_ts,
        )
