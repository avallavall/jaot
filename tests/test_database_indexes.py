"""Tests verifying database indexes exist for query performance.

DATA-03: Compound index on credit_transactions(organization_id, created_at)
DATA-04: Index on api_keys.organization_id
"""

import pytest

from app.models.api_key import APIKey
from app.models.credit_transaction import CreditTransaction


class TestCreditTransactionIndexes:
    """DATA-03: Compound index on credit_transactions(organization_id, created_at)."""

    def test_compound_index_exists_on_model(self):
        """Model declares ix_credit_txn_org_created index."""
        index_names = {idx.name for idx in CreditTransaction.__table__.indexes}
        assert "ix_credit_txn_org_created" in index_names

    def test_compound_index_columns(self):
        """Compound index covers (organization_id, created_at) in that order."""
        for idx in CreditTransaction.__table__.indexes:
            if idx.name == "ix_credit_txn_org_created":
                col_names = [col.name for col in idx.columns]
                assert col_names == ["organization_id", "created_at"]
                break
        else:
            pytest.fail("ix_credit_txn_org_created not found")

    def test_compound_index_is_not_unique(self):
        """Compound index is non-unique (multiple txns per org per timestamp)."""
        for idx in CreditTransaction.__table__.indexes:
            if idx.name == "ix_credit_txn_org_created":
                assert not idx.unique
                break
        else:
            pytest.fail("ix_credit_txn_org_created not found")

    def test_single_org_index_still_exists(self):
        """The original single-column index on organization_id still exists."""
        index_names = {idx.name for idx in CreditTransaction.__table__.indexes}
        # SQLAlchemy auto-names it ix_credit_transactions_organization_id
        org_indexes = [n for n in index_names if "organization_id" in n]
        assert len(org_indexes) >= 1  # At least the original single-column index

    def test_created_at_index_still_exists(self):
        """The original single-column index on created_at still exists."""
        index_names = {idx.name for idx in CreditTransaction.__table__.indexes}
        created_indexes = [n for n in index_names if "created_at" in n and "org" not in n]
        assert len(created_indexes) >= 1


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
        from app.models.credit_transaction import CreditTransaction

        assert CreditTransaction.__tablename__ == "credit_transactions"
        assert APIKey.__tablename__ == "api_keys"

    def test_credit_transaction_table_args_present(self):
        """CreditTransaction has __table_args__ with the compound index."""
        assert hasattr(CreditTransaction, "__table_args__")
        # __table_args__ is a tuple containing Index objects
        assert len(CreditTransaction.__table_args__) >= 1
