"""Seller analytics service for tracking and aggregating marketplace metrics.

Handles view/impression logging with geoIP lookup, and provides aggregation
queries for seller dashboards and admin analytics.

ADR-008: metrics are non-monetary — an "activation" is an ``OrganizationModel``
row created for a catalog model (someone adopted it), not a credit sale.
Self-activations (the author's own org) are excluded so the metric keeps its
"someone else adopted my model" meaning.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.model_project import ModelProjectListing
from app.models.model_view_event import ModelViewEvent
from app.models.optimization_model import ModelCatalog, OrganizationModel
from app.schemas.seller_analytics import (
    AnalyticsSummaryResponse,
    ConversionFunnelResponse,
    GeoDistributionEntry,
    GeoDistributionResponse,
    ModelPerformanceRow,
    SellerLeaderboardEntry,
    TimeSeriesDataPoint,
    TimeSeriesResponse,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Lazy-loaded geoIP instance
_geoip_reader: object | None = None


def _get_geoip_country(ip: str | None) -> str | None:
    """Look up ISO 3166-1 alpha-2 country code from an IP address.

    Uses geoip2fast for lightweight, file-based lookups.
    Returns None if lookup fails or ip is None/private.
    """
    if not ip:
        return None
    global _geoip_reader
    try:
        if _geoip_reader is None:
            from geoip2fast import GeoIP2Fast

            _geoip_reader = GeoIP2Fast()
        result = _geoip_reader.lookup(ip)  # type: ignore[union-attr]
        if result and result.country_code and result.country_code != "--":
            return result.country_code
    except Exception:
        logger.debug("GeoIP lookup failed for %s", ip, exc_info=True)
    return None


def _period_since(period: str) -> datetime | None:
    """Convert a period string to a since-datetime. Returns None for 'all'."""
    now = utcnow()
    mapping = {"7d": 7, "30d": 30, "90d": 90}
    days = mapping.get(period)
    if days is not None:
        return now - timedelta(days=days)
    return None  # "all" -- no filter


class SellerAnalyticsService:
    """Analytics service for seller dashboards and admin reporting."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def log_impression(
        self,
        model_project_ids: list[str],
        viewer_org_id: str | None = None,
        viewer_ip: str | None = None,
    ) -> None:
        """Batch-insert impression events for listings shown in a marketplace page."""
        country = _get_geoip_country(viewer_ip)
        events = [
            ModelViewEvent(
                id=generate_id("mve_"),
                model_project_id=model_id,
                event_type="impression",
                viewer_organization_id=viewer_org_id,
                viewer_country=country,
                created_at=utcnow(),
            )
            for model_id in model_project_ids
        ]
        self.db.add_all(events)
        self.db.flush()

    def log_view(
        self,
        model_project_id: str,
        viewer_org_id: str | None = None,
        viewer_ip: str | None = None,
    ) -> None:
        """Insert a single view event (user clicked into a marketplace detail page)."""
        country = _get_geoip_country(viewer_ip)
        event = ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=model_project_id,
            event_type="view",
            viewer_organization_id=viewer_org_id,
            viewer_country=country,
            created_at=utcnow(),
        )
        self.db.add(event)
        self.db.flush()

    def _base_view_query(self, org_id: str | None, since: datetime | None):  # noqa: ANN202
        """Build base query on model_view_events, optionally scoped to the author org."""
        q = self.db.query(ModelViewEvent)
        if org_id is not None:
            q = q.join(
                ModelProjectListing,
                ModelProjectListing.model_project_id == ModelViewEvent.model_project_id,
            ).filter(ModelProjectListing.author_organization_id == org_id)
        if since is not None:
            q = q.filter(ModelViewEvent.created_at >= since)
        return q

    def _base_activation_query(self, org_id: str | None, since: datetime | None):  # noqa: ANN202
        """Activations = OrganizationModel rows on the org's catalog models.

        Excludes the author org activating its own model.
        """
        q = self.db.query(OrganizationModel).join(
            ModelCatalog, ModelCatalog.id == OrganizationModel.catalog_id
        )
        if org_id is not None:
            q = q.filter(ModelCatalog.author_organization_id == org_id)
        q = q.filter(OrganizationModel.organization_id != ModelCatalog.author_organization_id)
        if since is not None:
            q = q.filter(OrganizationModel.created_at >= since)
        return q

    def get_summary(self, org_id: str | None, period: str) -> AnalyticsSummaryResponse:
        """Aggregate views, impressions, and activations."""
        since = _period_since(period)

        view_q = self._base_view_query(org_id, since)
        total_views = view_q.filter(ModelViewEvent.event_type == "view").count()
        total_impressions = view_q.filter(ModelViewEvent.event_type == "impression").count()

        total_activations = self._base_activation_query(org_id, since).count()

        conversion_rate = (total_activations / total_views * 100) if total_views > 0 else 0.0

        return AnalyticsSummaryResponse(
            total_views=total_views,
            total_impressions=total_impressions,
            total_activations=total_activations,
            conversion_rate=round(conversion_rate, 2),
            period=period,
        )

    def get_time_series(self, org_id: str | None, period: str) -> TimeSeriesResponse:
        """Daily aggregation of views, impressions, and activations."""
        since = _period_since(period)

        # Views + impressions per day
        view_q = self._base_view_query(org_id, since)
        daily_events = (
            view_q.with_entities(
                func.date(ModelViewEvent.created_at).label("day"),
                ModelViewEvent.event_type,
                func.count().label("cnt"),
            )
            .group_by(func.date(ModelViewEvent.created_at), ModelViewEvent.event_type)
            .all()
        )

        # Activations per day
        daily_activations = (
            self._base_activation_query(org_id, since)
            .with_entities(
                func.date(OrganizationModel.created_at).label("day"),
                func.count().label("activations"),
            )
            .group_by(func.date(OrganizationModel.created_at))
            .all()
        )

        # Merge into per-day map
        day_map: dict[str, dict[str, int]] = {}
        for row in daily_events:
            d = str(row.day)
            if d not in day_map:
                day_map[d] = {"views": 0, "impressions": 0, "activations": 0}
            if row.event_type == "view":
                day_map[d]["views"] = row.cnt
            else:
                day_map[d]["impressions"] = row.cnt

        for row in daily_activations:
            d = str(row.day)
            if d not in day_map:
                day_map[d] = {"views": 0, "impressions": 0, "activations": 0}
            day_map[d]["activations"] = row.activations

        data = [TimeSeriesDataPoint(date=d, **vals) for d, vals in sorted(day_map.items())]

        return TimeSeriesResponse(data=data, period=period)

    def get_geo_distribution(self, org_id: str | None, period: str) -> GeoDistributionResponse:
        """Group views by viewer_country."""
        since = _period_since(period)
        view_q = self._base_view_query(org_id, since)

        rows = (
            view_q.filter(ModelViewEvent.viewer_country.isnot(None))
            .with_entities(
                ModelViewEvent.viewer_country,
                func.count().label("cnt"),
            )
            .group_by(ModelViewEvent.viewer_country)
            .order_by(func.count().desc())
            .all()
        )

        data = [GeoDistributionEntry(country=row.viewer_country, count=row.cnt) for row in rows]
        return GeoDistributionResponse(data=data)

    def get_model_performance(self, org_id: str, period: str) -> list[ModelPerformanceRow]:
        """Per-model breakdown for a seller."""
        since = _period_since(period)

        # Views per model
        view_q = (
            self.db.query(
                ModelViewEvent.model_project_id,
                func.count().label("views"),
            )
            .join(
                ModelProjectListing,
                ModelProjectListing.model_project_id == ModelViewEvent.model_project_id,
            )
            .filter(
                ModelProjectListing.author_organization_id == org_id,
                ModelViewEvent.event_type == "view",
            )
        )
        if since is not None:
            view_q = view_q.filter(ModelViewEvent.created_at >= since)
        view_rows = view_q.group_by(ModelViewEvent.model_project_id).all()
        views_map = {r.model_project_id: r.views for r in view_rows}

        # Activations per model
        activation_rows = (
            self._base_activation_query(org_id, since)
            .with_entities(
                OrganizationModel.catalog_id,
                func.count().label("activations"),
            )
            .group_by(OrganizationModel.catalog_id)
            .all()
        )
        activations_map = {r.catalog_id: r.activations for r in activation_rows}

        all_model_ids = set(views_map.keys()) | set(activations_map.keys())
        if not all_model_ids:
            return []

        models = (
            self.db.query(ModelProjectListing.model_project_id, ModelProjectListing.display_name)
            .filter(ModelProjectListing.model_project_id.in_(all_model_ids))
            .all()
        )
        name_map = {m.model_project_id: m.display_name for m in models}

        result = []
        for model_id in all_model_ids:
            views = views_map.get(model_id, 0)
            activations = activations_map.get(model_id, 0)
            conv = (activations / views * 100) if views > 0 else 0.0
            result.append(
                ModelPerformanceRow(
                    model_id=model_id,
                    model_name=name_map.get(model_id, "Unknown"),
                    views=views,
                    activations=activations,
                    conversion_rate=round(conv, 2),
                )
            )

        return sorted(result, key=lambda r: r.activations, reverse=True)

    def get_conversion_funnel(self, org_id: str | None, period: str) -> ConversionFunnelResponse:
        """Impressions -> views -> activations funnel."""
        since = _period_since(period)
        view_q = self._base_view_query(org_id, since)

        impressions = view_q.filter(ModelViewEvent.event_type == "impression").count()
        views = view_q.filter(ModelViewEvent.event_type == "view").count()
        activations = self._base_activation_query(org_id, since).count()

        return ConversionFunnelResponse(
            impressions=impressions, views=views, activations=activations
        )

    def get_seller_leaderboard(self, period: str) -> list[SellerLeaderboardEntry]:
        """Admin-only leaderboard: top authors by adoption (activations)."""
        since = _period_since(period)

        activation_rows = (
            self._base_activation_query(org_id=None, since=since)
            .with_entities(
                ModelCatalog.author_organization_id.label("org_id"),
                func.count().label("total_activations"),
            )
            .group_by(ModelCatalog.author_organization_id)
            .all()
        )

        if not activation_rows:
            return []

        org_ids = [r.org_id for r in activation_rows]

        # Org names
        from app.models.organization import Organization  # noqa: PLC0415

        orgs = (
            self.db.query(Organization.id, Organization.name)
            .filter(Organization.id.in_(org_ids))
            .all()
        )
        org_name_map = {o.id: o.name for o in orgs}

        # Published models count per org
        model_counts = (
            self.db.query(
                ModelCatalog.author_organization_id,
                func.count().label("cnt"),
            )
            .filter(
                ModelCatalog.author_organization_id.in_(org_ids),
                ModelCatalog.status == "published",
            )
            .group_by(ModelCatalog.author_organization_id)
            .all()
        )
        models_map = {r.author_organization_id: r.cnt for r in model_counts}

        # Avg rating per org
        rating_rows = (
            self.db.query(
                ModelCatalog.author_organization_id,
                func.avg(ModelCatalog.avg_rating).label("avg_r"),
            )
            .filter(
                ModelCatalog.author_organization_id.in_(org_ids),
                ModelCatalog.avg_rating.isnot(None),
            )
            .group_by(ModelCatalog.author_organization_id)
            .all()
        )
        rating_map = {r.author_organization_id: round(float(r.avg_r), 2) for r in rating_rows}

        result = []
        for row in activation_rows:
            result.append(
                SellerLeaderboardEntry(
                    org_id=row.org_id,
                    org_name=org_name_map.get(row.org_id, "Unknown"),
                    total_activations=row.total_activations,
                    models_published=models_map.get(row.org_id, 0),
                    avg_rating=rating_map.get(row.org_id),
                )
            )

        return sorted(result, key=lambda r: r.total_activations, reverse=True)
