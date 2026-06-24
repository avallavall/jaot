"""Pydantic response schemas for feature usage analytics admin API."""

from pydantic import BaseModel


class FeatureAnalyticsKPI(BaseModel):
    """KPI summary for analytics dashboard."""

    total_events: int
    active_users: int
    events_today: int
    top_event_type: str | None
    top_event_count: int
    period: str
    prev_total_events: int | None = None
    prev_active_users: int | None = None
    prev_events_today: int | None = None


class FeatureTimeSeriesPoint(BaseModel):
    """Single data point in a time series chart."""

    date: str
    count: int
    event_type: str | None = None


class FeatureTimeSeriesResponse(BaseModel):
    """Time series response for trend charts."""

    data: list[FeatureTimeSeriesPoint]
    period: str


class EventBreakdownEntry(BaseModel):
    """Single entry in event type breakdown."""

    event_type: str
    count: int
    prev_count: int | None = None


class DomainSummaryEntry(BaseModel):
    """Single entry in domain summary (radar chart)."""

    domain: str
    count: int


class ConversionFunnelStep(BaseModel):
    """Single step in conversion funnel."""

    name: str
    value: int
    fill: str
    prev_value: int | None = None


class ConversionFunnelResponse(BaseModel):
    """Conversion funnel response."""

    steps: list[ConversionFunnelStep]


class RecentEventEntry(BaseModel):
    """Single recent event entry."""

    id: str
    event_type: str
    user_id: str
    country_code: str | None
    created_at: str
    metadata: dict | None


class CountryDistributionEntry(BaseModel):
    """Single entry in country distribution."""

    country_code: str
    count: int


class PaginatedRecentEventsResponse(BaseModel):
    """Paginated recent events response."""

    items: list[RecentEventEntry]
    total: int
    page: int
    page_size: int


class GroupedTimeSeriesPoint(BaseModel):
    """Single data point in a grouped time series chart."""

    date: str
    series: dict[str, int]


class GroupedTimeSeriesResponse(BaseModel):
    """Grouped time series response for multi-line charts."""

    data: list[GroupedTimeSeriesPoint]
    period: str
    group_by: str


class FeatureAnalyticsOverview(BaseModel):
    """Complete analytics overview combining all sections."""

    kpi: FeatureAnalyticsKPI
    time_series: FeatureTimeSeriesResponse
    event_breakdown: list[EventBreakdownEntry]
    domain_summary: list[DomainSummaryEntry]
    funnel: ConversionFunnelResponse
    country_distribution: list[CountryDistributionEntry]
    grouped_time_series: list[GroupedTimeSeriesPoint] | None = None
