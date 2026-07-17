"""P1.5 F3 — the marketplace-fusion backfill, unit-tested against real seed data.

Drives ``app.shared.db.p15_backfill.run_backfill`` (the exact logic the migration
runs) over representative legacy rows and asserts the shadow ModelProjects/listings
+ forward-FK links are correct, and that a second run is a no-op (idempotent).

# CONTRACT-TEST: the fusion backfill must preserve ids + map every legacy row.
"""

import pytest
from sqlalchemy import text

from app.models import (
    ModelCatalog,
    ModelCategory,
    ModelProject,
    ModelProjectListing,
    ModelReview,
    ModelViewEvent,
    OrganizationModel,
)
from app.models.favorite import RecentModel, UserFavorite
from app.shared.db.p15_backfill import SYSTEM_ORG_ID, revert_backfill, run_backfill

pytestmark = pytest.mark.contract


def _catalog(db, *, cid, official, author_org=None, **ov):
    fields = {
        "id": cid,
        "name": cid,
        "display_name": "Disp " + cid,
        "description": "desc",
        "category": ModelCategory.LOGISTICS,
        "generator_type": "knapsack",
        "input_schema": {"type": "object"},
        "input_fields": [{"name": "cap"}],
        "example_input": {"cap": 10},
        "version": "1.0.0",
        "status": "published",
        "is_official": official,
        "is_public": True,
        "author_organization_id": author_org,
        "tags": ["t1"],
    }
    fields.update(ov)
    row = ModelCatalog(**fields)
    db.add(row)
    return row


def _clean_marketplace(db):
    """Deterministic clean slate: app startup seeds 102 official catalog rows and
    other tests leave residue, which would skew the global backfill counts."""
    for t in (
        "model_view_events",
        "recent_models",
        "user_favorites",
        "model_reviews",
        "model_project_listings",
    ):
        db.execute(text(f"DELETE FROM {t}"))  # noqa: S608 — fixed table names
    db.execute(
        text(
            "DELETE FROM model_projects WHERE id IN (SELECT id FROM model_catalog) "
            "OR id IN (SELECT id FROM organization_models)"
        )
    )
    db.execute(text("DELETE FROM organization_models"))
    db.execute(text("DELETE FROM model_catalog"))
    db.commit()


class TestBackfill:
    def _seed(self, db, org, user):
        _clean_marketplace(db)
        # An official (no author org) + a community catalog (authored by the org).
        _catalog(db, cid="official_knap", official=True)
        _catalog(db, cid="comm_vrp", official=False, author_org=org.id, generator_type="generic")
        # Activated (catalog-linked), private (definition), and archived org-models.
        db.add(
            OrganizationModel(
                id="om_activated",
                organization_id=org.id,
                catalog_id="official_knap",
                is_active=True,
            )
        )
        db.add(
            OrganizationModel(
                id="om_private",
                organization_id=org.id,
                private_definition={"name": "My Private", "generator_type": "blend"},
                is_active=True,
            )
        )
        db.add(
            OrganizationModel(
                id="om_archived",
                organization_id=org.id,
                catalog_id="comm_vrp",
                custom_name="Renamed",
                is_active=False,
            )
        )
        # Commit the catalog + org-models first: the FK-source rows below reference
        # model_catalog, and these models carry no ORM relationship for SQLAlchemy to
        # order the inserts by (mirrors reality — catalog rows predate reviews/views).
        db.commit()
        # Forward-FK sources, all keyed by catalog id.
        db.add(
            ModelReview(
                id="rev_1",
                catalog_id="official_knap",
                user_id=user.id,
                organization_id=org.id,
                rating=5,
            )
        )
        db.add(UserFavorite(user_id=user.id, model_id="official_knap"))
        db.add(RecentModel(user_id=user.id, model_id="comm_vrp"))
        db.add(ModelViewEvent(catalog_model_id="official_knap", event_type="view"))
        db.commit()

    def test_backfill_maps_everything(self, db_session, test_organization, test_user):
        self._seed(db_session, test_organization, test_user)

        counts = run_backfill(db_session.connection())
        db_session.commit()
        db_session.expire_all()

        assert counts["projects_from_catalog"] == 2
        assert counts["listings"] == 2
        assert counts["projects_from_org_models"] == 3
        assert counts["reviews_linked"] == 1
        assert counts["favorites_linked"] == 1
        assert counts["recents_linked"] == 1
        assert counts["views_linked"] == 1

        # Official catalog → project owned by the SYSTEM org + a listing carrying the facet.
        official = db_session.get(ModelProject, "official_knap")
        assert official is not None
        assert official.organization_id == SYSTEM_ORG_ID
        assert official.source_type == "marketplace"
        listing = db_session.get(ModelProjectListing, "official_knap")
        assert listing is not None
        assert listing.is_official is True
        assert listing.generator_type == "knapsack"
        assert listing.category == ModelCategory.LOGISTICS.value
        assert listing.is_public is True
        assert listing.input_fields == [{"name": "cap"}]
        assert listing.example_input == {"cap": 10}

        # Community catalog → project owned by its AUTHOR org.
        comm = db_session.get(ModelProject, "comm_vrp")
        assert comm.organization_id == test_organization.id
        assert db_session.get(ModelProjectListing, "comm_vrp").is_official is False

        # Activated org-model → project in its own org, marketplace source_ref = catalog id.
        act = db_session.get(ModelProject, "om_activated")
        assert act.organization_id == test_organization.id
        assert act.source_type == "marketplace"
        assert act.source_ref == "official_knap"
        assert act.status == "active"
        assert act.name == "Disp official_knap"  # inherited from the catalog display_name
        # Private org-model → import source, name from private_definition.
        priv = db_session.get(ModelProject, "om_private")
        assert priv.source_type == "import"
        assert priv.source_ref is None
        assert priv.name == "My Private"
        # Archived org-model → archived status + custom_name wins.
        arch = db_session.get(ModelProject, "om_archived")
        assert arch.status == "archived"
        assert arch.archived_at is not None
        assert arch.name == "Renamed"

        # source_model_project_id stamped (id preserved → self).
        for oid in ("om_activated", "om_private", "om_archived"):
            om = db_session.get(OrganizationModel, oid)
            assert om.source_model_project_id == oid

        # Forward FKs point at the (same-id) project.
        assert db_session.get(ModelReview, "rev_1").model_project_id == "official_knap"
        fav = db_session.query(UserFavorite).filter_by(model_id="official_knap").one()
        assert fav.model_project_id == "official_knap"
        rec = db_session.query(RecentModel).filter_by(model_id="comm_vrp").one()
        assert rec.model_project_id == "comm_vrp"
        view = db_session.query(ModelViewEvent).filter_by(catalog_model_id="official_knap").one()
        assert view.model_project_id == "official_knap"

    def test_backfill_is_idempotent(self, db_session, test_organization, test_user):
        self._seed(db_session, test_organization, test_user)

        run_backfill(db_session.connection())
        db_session.commit()
        # A second pass creates nothing and does not raise.
        counts2 = run_backfill(db_session.connection())
        db_session.commit()
        db_session.expire_all()

        assert counts2 == {
            "projects_from_catalog": 0,
            "listings": 0,
            "projects_from_org_models": 0,
            "reviews_linked": 0,
            "favorites_linked": 0,
            "recents_linked": 0,
            "views_linked": 0,
        }
        # Exactly one project per legacy row (no duplicates).
        assert db_session.query(ModelProject).filter_by(id="official_knap").count() == 1
        assert db_session.query(ModelProjectListing).count() == 2

    def test_revert_undoes_the_backfill(self, db_session, test_organization, test_user):
        self._seed(db_session, test_organization, test_user)
        run_backfill(db_session.connection())
        db_session.commit()
        assert db_session.get(ModelProject, "official_knap") is not None

        revert_backfill(db_session.connection())
        db_session.commit()
        db_session.expire_all()

        # Shadow projects + listings gone; legacy rows + their forward FKs cleared.
        assert db_session.get(ModelProject, "official_knap") is None
        assert db_session.get(ModelProject, "om_activated") is None
        assert db_session.query(ModelProjectListing).count() == 0
        assert db_session.get(ModelReview, "rev_1").model_project_id is None
        assert db_session.get(OrganizationModel, "om_activated").source_model_project_id is None
        # The legacy catalog/org-model rows themselves survive (dual-read intact).
        assert db_session.get(ModelCatalog, "official_knap") is not None
        assert db_session.get(OrganizationModel, "om_activated") is not None

    def test_backfill_empty_db_is_noop(self, db_session):
        # No legacy rows → nothing created, no system org needed to persist, no error.
        _clean_marketplace(db_session)
        counts = run_backfill(db_session.connection())
        db_session.commit()
        assert all(v == 0 for v in counts.values())
