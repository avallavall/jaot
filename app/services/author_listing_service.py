"""What an author published, and what people said about it.

The sibling of ``author_analytics_service``: that one answers "how is it doing",
this one answers "what do I have out there" and "what came back". Both are
read-only views over ``ModelProjectListing`` scoped to the author organization.

Deliberately NOT filtered by :data:`MARKETPLACE_VISIBLE`: this is the author's
own view, where a withdrawn listing must still appear — it is the row they
restore from.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, load_only

from app.models import ModelProjectListing, ModelReview, User
from app.schemas.author import AuthorListingRow, AuthorReviewRow, AuthorReviewsResponse
from app.services.author_analytics_service import adoption_counts
from app.shared.utils.pagination import paginate_query

# Every field `AuthorListingRow` reads off the row. Add one to the schema and add
# it here, or the panel reads an unloaded attribute and pays a SELECT per row for
# it. `total_activations` is deliberately absent: it is counted, not stored.
_LISTING_ROW_COLUMNS = (
    ModelProjectListing.display_name,
    ModelProjectListing.short_description,
    ModelProjectListing.category,
    ModelProjectListing.status,
    ModelProjectListing.is_public,
    ModelProjectListing.version,
    ModelProjectListing.logo_url,
    ModelProjectListing.total_executions,
    ModelProjectListing.avg_rating,
    ModelProjectListing.success_rate,
    ModelProjectListing.published_at,
    ModelProjectListing.updated_at,
)


def load_my_listing_rows(db: Session, *, org_id: str) -> list[ModelProjectListing]:
    """The ORM rows behind :func:`list_my_listings`, newest first.

    Separate from the mapping above so the column set stays testable: the whole
    point of the ``load_only`` is what it does NOT read, and that is invisible
    once the rows have been turned into response objects.
    """
    return (
        db.query(ModelProjectListing)
        .options(load_only(*_LISTING_ROW_COLUMNS))
        .filter(ModelProjectListing.author_organization_id == org_id)
        .order_by(ModelProjectListing.updated_at.desc())
        .all()
    )


def list_my_listings(db: Session, *, org_id: str) -> list[AuthorListingRow]:
    """Everything this organization has published, whatever state it is in.

    Only the columns :class:`AuthorListingRow` serializes are read. The default
    entity load also pulled the five ``section_*`` markdown documents, the three
    generator JSON blobs (``input_schema``, ``input_fields``, ``example_input``)
    and both descriptions — kilobytes per row that this panel never renders, on
    a query with no upper bound on rows.

    Adoptions are counted, not read — see ``adoption_query``. One extra query
    covers every row of the panel.
    """
    listings = load_my_listing_rows(db, org_id=org_id)
    adoptions = adoption_counts(db, [row.model_project_id for row in listings])
    return [
        AuthorListingRow.model_validate(row).model_copy(
            update={"total_activations": adoptions.get(row.model_project_id, 0)}
        )
        for row in listings
    ]


def list_reviews_received(
    db: Session, *, org_id: str, page: int, page_size: int
) -> AuthorReviewsResponse:
    """Reviews left on any of this organization's models, newest first.

    Moderation is respected — a review an admin hid is not shown to the author
    either. Reviews on withdrawn listings still count: they were left on a model
    of theirs, and withdrawing it does not unsay them.
    """
    my_listings = (
        db.query(ModelProjectListing.model_project_id, ModelProjectListing.display_name)
        .filter(ModelProjectListing.author_organization_id == org_id)
        .all()
    )
    if not my_listings:
        return AuthorReviewsResponse(reviews=[], total=0)

    names = {row.model_project_id: row.display_name for row in my_listings}

    query = (
        db.query(ModelReview)
        .filter(
            ModelReview.model_project_id.in_(list(names)),
            ModelReview.is_visible == True,  # noqa: E712
        )
        .order_by(ModelReview.created_at.desc())
    )
    reviews, total = paginate_query(query, page, page_size)

    # Batch pre-fetch the reviewers (N+1 otherwise), same as the public endpoint.
    user_ids = list({r.user_id for r in reviews if r.user_id})
    users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    )

    rows = [
        AuthorReviewRow(
            id=review.id,
            model_project_id=review.model_project_id,
            # Every review here was matched against `names`, so the lookup holds.
            model_display_name=names[review.model_project_id],
            rating=review.rating,
            title=review.title,
            comment=review.comment,
            reviewer_name=_reviewer_name(users.get(review.user_id)),
            created_at=review.created_at,
        )
        for review in reviews
    ]
    return AuthorReviewsResponse(reviews=rows, total=total)


def _reviewer_name(user: User | None) -> str | None:
    """Display name, falling back to the account name; None if the user is gone."""
    if user is None:
        return None
    return user.display_name or user.name
