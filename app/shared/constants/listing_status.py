"""The publication lifecycle of a marketplace listing.

Persisted on ``ModelProjectListing.status``. The values were bare strings spread
across the codebase until the reversible withdrawal landed (2026-07-31) and made
the difference between them load-bearing: "the row exists" stopped meaning "it is
on the marketplace", and every surface that had conflated the two started handing
readers links to pages that answer 404.

``DRAFT``      — a listing that has never been through ``publish_listing`` (its
                 checks, its version pin). Legacy backfilled rows can sit here.
``PUBLISHED``  — on the marketplace, subject to ``is_public`` as well.
``UNPUBLISHED``— withdrawn by its author, reversibly: the row and all its rollups
                 survive so republishing restores it as it was.
``DEPRECATED`` — an official template the seeder retired; never author-driven.

Only ``PUBLISHED <-> UNPUBLISHED`` is a legal round trip (``AUTHOR_TOGGLEABLE``).
Anything else has to go through publishing, which is what enforces the invariants
the other two states have not satisfied.
"""

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_UNPUBLISHED = "unpublished"
STATUS_DEPRECATED = "deprecated"

VALID_LISTING_STATUSES = frozenset(
    {
        STATUS_DRAFT,
        STATUS_PUBLISHED,
        STATUS_UNPUBLISHED,
        STATUS_DEPRECATED,
    }
)

# The pair an author can move a listing between from the author area.
AUTHOR_TOGGLEABLE = frozenset({STATUS_PUBLISHED, STATUS_UNPUBLISHED})
