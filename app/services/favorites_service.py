"""Favourites and recently-opened models — the data layer behind those routes.

The queries used to sit in ``app/api/v2/routes/models/favorites.py`` (D-19/F-09:
the route layer was also the data layer). They are here so the user scoping is
written once, and so the routes read as what they are — four lookups and two
list views.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import (
    ModelProject,
    ModelProjectListing,
    Organization,
    RecentModel,
    UserFavorite,
)
from app.schemas.model import (
    FavoriteListResponse,
    FavoriteModelSummary,
    RecentListResponse,
    RecentModelSummary,
)


def _author_names(db: Session, listings: list[ModelProjectListing]) -> dict[str, str]:
    """Resolve each listing's author-org display name, keyed by model_project_id.

    Backfilled/legacy listings may lack ``author_organization_id`` (the legacy
    catalog never carried it) — fall back to the owning project's organization,
    which in the fused model IS the publisher.
    """
    project_orgs: dict[str, str] = {}
    missing = [s.model_project_id for s in listings if not s.author_organization_id]
    if missing:
        rows = (
            db.query(ModelProject.id, ModelProject.organization_id)
            .filter(ModelProject.id.in_(missing))
            .all()
        )
        project_orgs = {pid: oid for pid, oid in rows if oid}

    org_ids = {s.author_organization_id for s in listings if s.author_organization_id}
    org_ids.update(project_orgs.values())
    orgs = (
        {o.id: o.name for o in db.query(Organization).filter(Organization.id.in_(org_ids)).all()}
        if org_ids
        else {}
    )

    names: dict[str, str] = {}
    for s in listings:
        org_id = s.author_organization_id or project_orgs.get(s.model_project_id)
        names[s.model_project_id] = orgs.get(org_id, "Unknown") if org_id else "Unknown"
    return names


def list_favorites(db: Session, user_id: str) -> FavoriteListResponse:
    """Every model this user has favourited, as marketplace cards."""
    favorites = db.query(UserFavorite).filter(UserFavorite.user_id == user_id).all()
    model_ids = [f.model_project_id for f in favorites if f.model_project_id]
    if not model_ids:
        return FavoriteListResponse(items=[], total=0)

    listings = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id.in_(model_ids))
        .all()
    )
    authors = _author_names(db, listings)

    items = [
        FavoriteModelSummary(
            id=listing.model_project_id,
            name=listing.name,
            display_name=listing.display_name,
            description=listing.description,
            category=listing.category or "general",
            author_name=authors[listing.model_project_id],
            is_official=listing.is_official,
            is_featured=listing.is_featured,
            avg_rating=listing.avg_rating,
        )
        for listing in listings
    ]
    return FavoriteListResponse(items=items, total=len(items))


def find_favorite(db: Session, user_id: str, model_id: str) -> UserFavorite | None:
    """This user's favourite row for one model, if any."""
    return (
        db.query(UserFavorite)
        .filter(
            UserFavorite.user_id == user_id,
            UserFavorite.model_project_id == model_id,
        )
        .first()
    )


def listing_exists(db: Session, model_id: str) -> bool:
    """Whether the marketplace still carries this model."""
    return (
        db.query(ModelProjectListing.model_project_id)
        .filter(ModelProjectListing.model_project_id == model_id)
        .first()
        is not None
    )


def add_favorite(db: Session, user_id: str, model_id: str) -> None:
    """Favourite a model. Doing it twice is not an error, it is a no-op."""
    if find_favorite(db, user_id, model_id) is not None:
        return
    db.add(UserFavorite(user_id=user_id, model_project_id=model_id))
    db.commit()


def remove_favorite(db: Session, user_id: str, model_id: str) -> None:
    """Un-favourite a model. Removing one that is not there is a no-op."""
    favorite = find_favorite(db, user_id, model_id)
    if favorite is not None:
        db.delete(favorite)
        db.commit()


def list_recents(db: Session, user_id: str, limit: int) -> RecentListResponse:
    """The models this user opened most recently, newest first."""
    recents = (
        db.query(RecentModel)
        .filter(RecentModel.user_id == user_id)
        .order_by(RecentModel.last_accessed.desc())
        .limit(limit)
        .all()
    )
    model_ids = [r.model_project_id for r in recents if r.model_project_id]
    if not model_ids:
        return RecentListResponse(items=[], total=0)

    listings = {
        s.model_project_id: s
        for s in db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id.in_(model_ids))
        .all()
    }
    authors = _author_names(db, list(listings.values()))

    # Driven by `recents`, not by `listings`: the order is the recency order, and
    # a model whose listing has since been unpublished simply drops out.
    items = [
        RecentModelSummary(
            id=listing.model_project_id,
            name=listing.name,
            display_name=listing.display_name,
            category=listing.category or "general",
            author_name=authors[listing.model_project_id],
            last_accessed=recent.last_accessed,
            access_count=recent.access_count,
        )
        for recent in recents
        if (listing := listings.get(recent.model_project_id)) is not None
    ]
    return RecentListResponse(items=items, total=len(items))
