"""Pydantic schemas for seller analytics API responses."""

from pydantic import BaseModel


class AnalyticsSummaryResponse(BaseModel):
    """Aggregated analytics summary for a time period."""

    total_views: int
    total_impressions: int
    total_activations: int
    total_revenue: int  # credits earned
    conversion_rate: float  # views -> activations
    period: str  # "7d", "30d", "90d", "all"


class TimeSeriesDataPoint(BaseModel):
    """Single data point in a time series."""

    date: str  # YYYY-MM-DD
    views: int
    impressions: int
    activations: int
    revenue: int


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
    """Per-model performance breakdown for a seller."""

    model_id: str
    model_name: str
    views: int
    activations: int
    revenue: int
    conversion_rate: float


class ConversionFunnelResponse(BaseModel):
    """Conversion funnel: impressions -> views -> activations."""

    impressions: int
    views: int
    activations: int


class SellerLeaderboardEntry(BaseModel):
    """Leaderboard entry for a seller (admin view)."""

    org_id: str
    org_name: str
    total_sales: int
    total_revenue: int
    models_published: int
    avg_rating: float | None


class AdminAnalyticsResponse(BaseModel):
    """Platform-wide analytics for admin dashboard."""

    platform_totals: AnalyticsSummaryResponse
    sellers: list[SellerLeaderboardEntry]
