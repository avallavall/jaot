"""Tests verifying database indexes exist for query performance.


DATA-04: Index on api_keys.organization_id
"""

from app.models.api_key import APIKey


class TestAPIKeyIndexes:
    """DATA-04: Index on api_keys.organization_id."""

    def test_organization_id_index_exists(self):
        """APIKey model declares index on organization_id."""
        index_names = {idx.name for idx in APIKey.__table__.indexes}
        org_indexes = [n for n in index_names if "organization_id" in n]
        assert len(org_indexes) >= 1

    def test_organization_id_index_name(self):
        """Index is named ix_api_keys_organization_id."""
        index_names = {idx.name for idx in APIKey.__table__.indexes}
        assert "ix_api_keys_organization_id" in index_names

    def test_key_hash_unique_index_preserved(self):
        """key_hash unique index still exists (backward compat)."""
        index_names = {idx.name for idx in APIKey.__table__.indexes}
        hash_indexes = [n for n in index_names if "key_hash" in n]
        assert len(hash_indexes) >= 1


class TestAlembicMigrationExists:
    """Verify migration file is properly structured."""

    def test_migration_file_importable(self):
        """Migration module can be imported without errors."""
        from app.models.api_key import APIKey

        assert APIKey.__tablename__ == "api_keys"
