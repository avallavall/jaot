"""Integration tests for official marketplace seeding (P1.5 fused entity).

Verifies that seed_official_models:
- Creates ModelProject anchors + published listings from YAML templates in a fresh DB
- Is idempotent (running twice produces no duplicates)
- Deprecates stale listings no longer in YAML source
- Completes in a reasonable time
- Seeds >= 100 official published models
"""

import time

from app.data.templates import load_all_templates
from app.models import ModelProject, ModelProjectListing
from app.shared.db.p15_backfill import SYSTEM_ORG_ID
from app.shared.db.seed_models import seed_official_models


def _published_officials(db_session):
    return db_session.query(ModelProjectListing).filter(
        ModelProjectListing.is_official.is_(True),
        ModelProjectListing.status == "published",
    )


class TestSeedOfficialModels:
    """Integration tests for the seed_official_models function."""

    def test_seed_creates_listings(self, db_session):
        """seed_official_models creates project+listing pairs from YAML templates."""
        count = seed_official_models(db_session)
        db_session.flush()

        db_count = _published_officials(db_session).count()

        assert count > 0
        assert db_count == count

    def test_seed_is_idempotent(self, db_session):
        """Running seed twice produces no duplicate entries."""
        count1 = seed_official_models(db_session)
        db_session.flush()

        count2 = seed_official_models(db_session)
        db_session.flush()

        assert count1 == count2

        # Verify no duplicates -- total published should equal single seed count
        assert _published_officials(db_session).count() == count1

    def test_seed_completes_under_5_seconds(self, db_session):
        """Seed completes in under 5 seconds."""
        start = time.monotonic()
        seed_official_models(db_session)
        db_session.flush()
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"Seeding took {elapsed:.1f}s, expected < 5s"

    def test_seed_creates_at_least_100_models(self, db_session):
        """After seeding, DB contains >= 100 official published models."""
        seed_official_models(db_session)
        db_session.flush()

        db_count = _published_officials(db_session).count()

        assert db_count >= 100, f"Expected >= 100 models, got {db_count}"

    def test_seed_deprecates_stale_models(self, db_session):
        """Seed deprecates official listings that are no longer in YAML source."""
        # First seed
        seed_official_models(db_session)
        db_session.flush()

        # Manually add a fake official listing (with its anchor project)
        db_session.add(
            ModelProject(
                id="official_fake_stale_model",
                organization_id=SYSTEM_ORG_ID,
                name="Fake Stale Model",
                status="active",
                source_type="official",
            )
        )
        db_session.flush()
        fake = ModelProjectListing(
            model_project_id="official_fake_stale_model",
            name="fake_stale_model",
            display_name="Fake Stale Model",
            description="A model that should be deprecated on next seed",
            short_description="Stale",
            category="production",
            tags=[],
            generator_type="generic",
            input_schema={"type": "object", "properties": {}, "required": []},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=True,
            is_featured=False,
            is_public=True,
        )
        db_session.add(fake)
        db_session.flush()

        # Re-seed -- fake listing should be deprecated
        seed_official_models(db_session)
        db_session.flush()

        refreshed = db_session.get(ModelProjectListing, "official_fake_stale_model")

        assert refreshed is not None
        assert refreshed.status == "deprecated"

    def test_seed_sets_correct_fields(self, db_session):
        """Seeded listings have all expected fields set correctly."""
        seed_official_models(db_session)
        db_session.flush()

        templates = load_all_templates()
        first_template = templates[0]
        listing_id = f"official_{first_template.id}"

        listing = db_session.get(ModelProjectListing, listing_id)

        assert listing is not None
        assert listing.name == first_template.name
        assert listing.display_name == first_template.display_name
        assert listing.generator_type == first_template.generator_type
        assert listing.is_official is True
        assert listing.is_public is True
        assert listing.status == "published"

        # The anchor project is owned by the system org
        project = db_session.get(ModelProject, listing_id)
        assert project is not None
        assert project.organization_id == SYSTEM_ORG_ID
