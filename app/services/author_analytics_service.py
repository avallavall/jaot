"""Author analytics service for tracking and aggregating marketplace metrics.

Handles view/impression logging with geoIP lookup, and provides aggregation
queries for author dashboards and admin analytics.

ADR-008: metrics are non-monetary — an "activation" is a fork ``ModelProject``
seeded from a listing via from-marketplace (someone adopted the model), not a
credit sale. Self-activations (the author's own org forking its own listing)
are excluded so the metric keeps its "someone else adopted my model" meaning.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.model_project import ModelProject, ModelProjectListing
from app.models.model_view_event import ModelViewEvent
from app.schemas.author_analytics import (
    AnalyticsSummaryResponse,
    AuthorLeaderboardEntry,
    ConversionFunnelResponse,
    GeoDistributionEntry,
    GeoDistributionResponse,
    ModelPerformanceRow,
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


def adoption_query(
    db: Session,
    *,
    author_org_id: str | None = None,
    since: datetime | None = None,
):  # noqa: ANN201
    """The one definition of "somebody adopted a marketplace model".

    An adoption is a ``ModelProject`` seeded from a listing through
    from-marketplace: ``source_type="marketplace"`` and ``source_ref`` pointing
    at a listing that still exists. The author's own organization forking its
    own listing does not count, or the number would not mean what the word says.

    This lives at module level because it used to live in three places at once.
    The admin dashboard counted every project tagged ``source_type="marketplace"``
    with no join and no exclusion, this service applied both, and the listings
    carried a stored ``total_activations`` counter bumped on a third rule. All
    three were shown to an admin under the word "adoption", two orders of
    magnitude apart: 112, 6 and 66 on the development database. The 112 was the
    worst of them — 105 of those projects carry ``source_ref = NULL``, so they
    record no source at all and were never an adoption of anything. The stored
    counter is gone; this is the only definition left.

    It counts the fork rows that exist right now, so it is "how many teams have
    this model" and not "how many times it was ever taken". An adopter who
    deletes their copy takes their adoption with them, and the figure goes down.
    That is the same number the author dashboard and the admin panel have shown
    since they were unified on this query, and the marketplace card now agrees
    with them. The immutable tally lives in the ``marketplace.activate``
    analytics events, which nothing displays.

    Args:
        author_org_id: Narrow to listings written by this organization.
        since: Only adoptions created on or after this moment.
    """
    q = (
        db.query(ModelProject)
        .join(
            ModelProjectListing,
            ModelProjectListing.model_project_id == ModelProject.source_ref,
        )
        .filter(ModelProject.source_type == "marketplace")
    )
    if author_org_id is not None:
        q = q.filter(ModelProjectListing.author_organization_id == author_org_id)
    # `is_distinct_from`, not `!=`: `author_organization_id` is nullable, and in
    # SQL `x != NULL` is NULL rather than true, so a plain `!=` DROPS every
    # adoption of a listing with no author org. Measured on the development
    # database: 3 listings of 112 have a NULL author org, and they carried 4 of
    # the 6 adoptions on the platform. The page reported 2.
    q = q.filter(
        ModelProject.organization_id.is_distinct_from(ModelProjectListing.author_organization_id)
    )
    if since is not None:
        q = q.filter(ModelProject.created_at >= since)
    return q


def adoption_counts(
    db: Session,
    listing_ids: Sequence[str] | None = None,
    *,
    author_org_id: str | None = None,
    since: datetime | None = None,
) -> dict[str, int]:
    """How many adoptions each listing has, keyed by listing id, in one query.

    The only grouped form of :func:`adoption_query`. A catalogue page renders up
    to fifty cards, so counting one card at a time would run fifty queries; this
    runs one. Listings with no adoption are absent from the result — callers
    default to 0.

    Args:
        listing_ids: Narrow to these listings. ``None`` means every listing the
            other arguments allow; an empty sequence means none, and returns {}.
        author_org_id: Narrow to listings written by this organization.
        since: Only adoptions created on or after this moment.
    """
    if listing_ids is not None:
        ids = list(listing_ids)
        if not ids:
            return {}
    else:
        ids = None
    q = adoption_query(db, author_org_id=author_org_id, since=since)
    if ids is not None:
        q = q.filter(ModelProjectListing.model_project_id.in_(ids))
    rows = (
        q.with_entities(
            ModelProjectListing.model_project_id.label("listing_id"),
            func.count().label("adoptions"),
        )
        .group_by(ModelProjectListing.model_project_id)
        .all()
    )
    return {row.listing_id: row.adoptions for row in rows}


def adoption_count(db: Session, listing_id: str) -> int:
    """How many adoptions one listing has. See :func:`adoption_counts`."""
    return adoption_counts(db, [listing_id]).get(listing_id, 0)


class AuthorAnalyticsService:
    """Analytics service for author dashboards and admin reporting."""

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
        """Adoptions, optionally scoped to one author org. See `adoption_query`."""
        return adoption_query(self.db, author_org_id=org_id, since=since)

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
                func.date(ModelProject.created_at).label("day"),
                func.count().label("activations"),
            )
            .group_by(func.date(ModelProject.created_at))
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
        """Group VIEWS by viewer_country.

        ``_base_view_query`` carries both event types, and impressions outnumber
        views by roughly thirty to one, so leaving the type unfiltered reported
        impression counts under a heading that says visits — and made the total
        exceed the view count it is supposed to break down.
        """
        since = _period_since(period)
        view_q = self._base_view_query(org_id, since).filter(ModelViewEvent.event_type == "view")

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
        """Per-model breakdown for an author."""
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

        # Activations per model, keyed by the forked listing's project id — the
        # same id space as views, since a fork's source_ref IS the listing id.
        activations_map = adoption_counts(self.db, author_org_id=org_id, since=since)

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

    def get_author_leaderboard(self, period: str) -> list[AuthorLeaderboardEntry]:
        """Admin-only leaderboard of the platform's authors, ranked by adoption.

        Driven by who has PUBLISHED, not by who has been adopted. Built from its
        own ranking metric, the panel could only ever show authors somebody had
        already forked: on a platform with 112 listings by 2 organizations it
        read "No author data available" for the period it opens on, because
        nobody had adopted anything in those 30 days. An author with published
        models and no adoptions yet is exactly who an admin opens this page to
        find, so they get a row with a zero.

        An org that has since unpublished still appears while its adoptions are
        in the period — the adoptions happened.

        ``models_published`` and ``avg_rating`` are all-time on purpose. The
        period ranks adoption; "models published in the last 7 days" is a
        different question and not the one this column answers.

        Adoptions of a listing with no author organization count in the platform
        total but belong to nobody, so they appear in no row here.
        """
        since = _period_since(period)

        activation_rows = (
            self._base_activation_query(org_id=None, since=since)
            .filter(ModelProjectListing.author_organization_id.isnot(None))
            .with_entities(
                ModelProjectListing.author_organization_id.label("org_id"),
                func.count().label("total_activations"),
            )
            .group_by(ModelProjectListing.author_organization_id)
            .all()
        )
        activations = {r.org_id: r.total_activations for r in activation_rows}

        # Published listings per org. This is also the author set: everyone with
        # something on the marketplace belongs on the leaderboard.
        model_counts = (
            self.db.query(
                ModelProjectListing.author_organization_id.label("org_id"),
                func.count().label("cnt"),
            )
            .filter(
                ModelProjectListing.author_organization_id.isnot(None),
                ModelProjectListing.status == "published",
            )
            .group_by(ModelProjectListing.author_organization_id)
            .all()
        )
        models_map = {r.org_id: r.cnt for r in model_counts}

        org_ids = sorted(set(models_map) | set(activations))
        if not org_ids:
            return []

        # Org names
        from app.models.organization import Organization  # noqa: PLC0415

        orgs = (
            self.db.query(Organization.id, Organization.name)
            .filter(Organization.id.in_(org_ids))
            .all()
        )
        org_name_map = {o.id: o.name for o in orgs}

        # Avg rating per org
        rating_rows = (
            self.db.query(
                ModelProjectListing.author_organization_id,
                func.avg(ModelProjectListing.avg_rating).label("avg_r"),
            )
            .filter(
                ModelProjectListing.author_organization_id.in_(org_ids),
                ModelProjectListing.avg_rating.isnot(None),
            )
            .group_by(ModelProjectListing.author_organization_id)
            .all()
        )
        rating_map = {r.author_organization_id: round(float(r.avg_r), 2) for r in rating_rows}

        result = [
            AuthorLeaderboardEntry(
                org_id=org_id,
                org_name=org_name_map.get(org_id, "Unknown"),
                total_activations=activations.get(org_id, 0),
                models_published=models_map.get(org_id, 0),
                avg_rating=rating_map.get(org_id),
            )
            for org_id in org_ids
        ]

        # Adoption first, then who published most, then the name — so two authors
        # on zero adoptions come back in the same order on every load.
        return sorted(
            result,
            key=lambda r: (-r.total_activations, -r.models_published, r.org_name),
        )
