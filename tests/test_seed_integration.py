"""Integration tests for official model catalog seeding.

Verifies that seed_official_models:
- Creates catalog entries from YAML templates in a fresh DB
- Is idempotent (running twice produces no duplicates)
- Deprecates stale models no longer in YAML source
- Completes in a reasonable time
- Seeds >= 100 official published models
"""

import time

from app.data.templates import load_all_templates
from app.models import ModelCatalog
from app.shared.db.seed_models import seed_official_models


class TestSeedOfficialModels:
    """Integration tests for the seed_official_models function."""

    def test_seed_creates_catalog_entries(self, db_session):
        """seed_official_models creates catalog entries from YAML templates in a fresh DB."""
        count = seed_official_models(db_session)
        db_session.flush()

        db_count = (
            db_session.query(ModelCatalog)
            .filter(
                ModelCatalog.is_official.is_(True),
                ModelCatalog.status == "published",
            )
            .count()
        )

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
        db_count = (
            db_session.query(ModelCatalog)
            .filter(
                ModelCatalog.is_official.is_(True),
                ModelCatalog.status == "published",
            )
            .count()
        )
        assert db_count == count1

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

        db_count = (
            db_session.query(ModelCatalog)
            .filter(
                ModelCatalog.is_official.is_(True),
                ModelCatalog.status == "published",
            )
            .count()
        )

        assert db_count >= 100, f"Expected >= 100 models, got {db_count}"

    def test_seed_deprecates_stale_models(self, db_session):
        """Seed deprecates official models that are no longer in YAML source."""
        # First seed
        seed_official_models(db_session)
        db_session.flush()

        # Manually add a fake official model
        fake = ModelCatalog(
            id="official_fake_stale_model",
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
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(fake)
        db_session.flush()

        # Re-seed -- fake model should be deprecated
        seed_official_models(db_session)
        db_session.flush()

        refreshed = (
            db_session.query(ModelCatalog)
            .filter(ModelCatalog.id == "official_fake_stale_model")
            .first()
        )

        assert refreshed is not None
        assert refreshed.status == "deprecated"

    def test_seed_sets_correct_fields(self, db_session):
        """Seeded models have all expected fields set correctly."""
        seed_official_models(db_session)
        db_session.flush()

        templates = load_all_templates()
        first_template = templates[0]
        catalog_id = f"official_{first_template.id}"

        model = db_session.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()

        assert model is not None
        assert model.name == first_template.name
        assert model.display_name == first_template.display_name
        assert model.generator_type == first_template.generator_type
        assert model.is_official is True
        assert model.is_public is True
        assert model.status == "published"
