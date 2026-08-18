"""
Tests for the catalog rating filter parameter (MKT-09; price filters died with ADR-008).

Tests the min_rating query parameter added to GET /api/v2/models/catalog, served from
the unified ``ModelProjectListing`` facet (P1.5 fusion).
"""

from app.models import ModelCategory, ModelProject, ModelProjectListing


def _make_listing(db, org, *, pid, avg_rating) -> None:
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="Test",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            avg_rating=avg_rating,
        )
    )
    db.commit()


class TestCatalogRatingFilter:
    """Tests for minimum rating filter on catalog endpoint."""

    def test_min_rating_filter(self, authenticated_client, db_session, test_organization):
        """Catalog filters models by minimum rating."""
        for i, rating in enumerate([1.0, 2.5, 3.5, 4.8]):
            _make_listing(db_session, test_organization, pid=f"rating_test_{i}", avg_rating=rating)

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(item["avg_rating"] >= 3 for item in items)

    def test_min_rating_with_no_rating_excluded(
        self, authenticated_client, db_session, test_organization
    ):
        """Models with no rating are excluded when min_rating is set."""
        _make_listing(db_session, test_organization, pid="rated_model", avg_rating=4.0)
        _make_listing(db_session, test_organization, pid="unrated_model", avg_rating=None)

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        ids = [item["id"] for item in items]
        assert "rated_model" in ids
        assert "unrated_model" not in ids


def _tied_listing(db, org, *, pid, executions=0, rating=None) -> None:
    """A listing that ties with every other one on both sort keys."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="Test",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            total_executions=executions,
            avg_rating=rating,
        )
    )


def _walk_every_page(client, sort_by: str, page_size: int = 5) -> tuple[list[str], int]:
    """Collect the ids the catalogue serves across all of its pages."""
    served: list[str] = []
    page, total = 1, 0
    while page <= 50:
        resp = client.get(
            "/api/v2/models/catalog",
            params={"page": page, "page_size": page_size, "sort_by": sort_by},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        total = body["total"]
        if not body["items"]:
            break
        served.extend(item["id"] for item in body["items"])
        page += 1
    return served, total


class TestCatalogPagingReachesEveryModel:
    """Browsing every page must show every published model, exactly once.

    All three sort keys tie constantly — most listings share an execution count
    and a rating, or have no rating at all — and OFFSET/LIMIT gives Postgres no
    reason to order tied rows the same way twice. Walking the local catalogue
    served 109 slots for 109 listings but only 99 DISTINCT models under
    `popular` and 102 under `rating`: ten published models that a visitor could
    not reach by browsing, and four served twice.
    """

    # CONTRACT-TEST: paging the catalogue reaches every listing exactly once
    def test_every_model_is_reachable_when_they_all_tie(
        self, client, db_session, test_organization
    ):
        for index in range(23):
            _tied_listing(db_session, test_organization, pid="mp_tie_%02d" % index)
        db_session.commit()

        for sort_by in ("popular", "rating", "newest"):
            served, total = _walk_every_page(client, sort_by)
            assert len(served) == total, "%s served %d slots for %d listings" % (
                sort_by,
                len(served),
                total,
            )
            assert len(set(served)) == total, (
                "%s reached %d distinct models out of %d — %d unreachable"
                % (sort_by, len(set(served)), total, total - len(set(served)))
            )

    def test_the_same_page_comes_back_the_same_twice(self, client, db_session, test_organization):
        for index in range(23):
            _tied_listing(db_session, test_organization, pid="mp_stable_%02d" % index)
        db_session.commit()

        for sort_by in ("popular", "rating", "newest"):
            first, _ = _walk_every_page(client, sort_by)
            second, _ = _walk_every_page(client, sort_by)
            assert first == second, "%s ordered its pages differently on the second walk" % sort_by
