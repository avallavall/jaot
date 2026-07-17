"""Pydantic schemas for author analytics API responses.

ADR-008: all metrics are non-monetary — "activation" means an org activated
the author's catalog model, not a credit sale.
"""

from pydantic import BaseModel


class AnalyticsSummaryResponse(BaseModel):
    """Aggregated analytics summary for a time period."""

    total_views: int
    total_impressions: int
    total_activations: int
    conversion_rate: float  # views -> activations
    period: str  # "7d", "30d", "90d", "all"


class TimeSeriesDataPoint(BaseModel):
    """Single data point in a time series."""

    date: str  # YYYY-MM-DD
    views: int
    impressions: int
    activations: int


class TimeSeriesResponse(BaseModel):
    """Daily time series analytics data."""

    data: list[TimeSeriesDataPoint]
    period: str


class GeoDistributionEntry(BaseModel):
    """Geographic distribution entry."""

    country: str  # 2-char ISO 3166-1 alpha-2
    count: int


class GeoDistributionResponse(BaseModel):
    """Geographic distribution of views."""

    data: list[GeoDistributionEntry]


class ModelPerformanceRow(BaseModel):
    """Per-model performance breakdown for an author."""

    model_id: str
    model_name: str
    views: int
    activations: int
    conversion_rate: float


class ConversionFunnelResponse(BaseModel):
    """Conversion funnel: impressions -> views -> activations."""

    impressions: int
    views: int
    activations: int


# Class name is an openapi schema name (wire) — renamed in the contract release.
class SellerLeaderboardEntry(BaseModel):
    """Leaderboard entry for a model author (admin view)."""

    org_id: str
    org_name: str
    total_activations: int
    models_published: int
    avg_rating: float | None


class AdminAnalyticsResponse(BaseModel):
    """Platform-wide analytics for admin dashboard."""

    platform_totals: AnalyticsSummaryResponse
    sellers: list[SellerLeaderboardEntry]
