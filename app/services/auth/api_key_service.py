"""API Key management service."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import APIKey, Organization, User
from app.shared.utils.datetime_helpers import is_expired, utcnow
from app.shared.utils.db_helpers import (
    get_api_key_by_hash,
    get_organization_or_none,
    get_user_or_none,
)
from app.shared.utils.id_generator import generate_api_key, generate_id, hash_api_key

logger = logging.getLogger(__name__)


class APIKeyService:
    """Service for managing API Keys."""

    @staticmethod
    def generate_key(prefix: str = "ok_live_") -> tuple[str, str]:
        """Generate a new API key.

        Args:
            prefix: Key prefix (e.g., "ok_live_" or "ok_test_")

        Returns:
            Tuple of (full_key, key_hash)
        """
        return generate_api_key(prefix)

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key.

        Args:
            key: Full API key

        Returns:
            SHA-256 hash of the key
        """
        return hash_api_key(key)

    @staticmethod
    def create_api_key(
        db: Session,
        user_id: str,
        organization_id: str,
        name: str | None = None,
        description: str | None = None,
        prefix: str = "ok_live_",
        expires_at: datetime | None = None,
    ) -> tuple[APIKey, str]:
        """Create a new API key.

        Args:
            db: Database session
            user_id: User ID
            organization_id: Organization ID
            name: Optional friendly name
            description: Optional description
            prefix: Key prefix
            expires_at: Optional expiration date

        Returns:
            Tuple of (APIKey model, plaintext_key)
        """
        full_key, key_hash = APIKeyService.generate_key(prefix)
        key_id = generate_id("key_")

        api_key = APIKey(
            id=key_id,
            key_hash=key_hash,
            key_prefix=prefix,
            user_id=user_id,
            organization_id=organization_id,
            name=name or "API Key",
            description=description,
            is_active=True,
            expires_at=expires_at,
        )

        db.add(api_key)
        db.flush()
        db.refresh(api_key)
        db.commit()

        return api_key, full_key

    @staticmethod
    def verify_key(db: Session, key: str) -> tuple[APIKey, User, Organization] | None:
        """Verify an API key and return associated models.

        Args:
            db: Database session
            key: Full API key to verify

        Returns:
            Tuple of (APIKey, User, Organization) if valid, None otherwise
        """
        from app.config import settings
        from app.services.platform_settings_service import (
            PlatformSettingsService as PSS,
        )

        live_prefix = PSS.get_str(db, "API_KEY_DEFAULT_PREFIX")
        test_prefix = PSS.get_str(db, "API_KEY_TEST_PREFIX")

        if not key.startswith(live_prefix) and not key.startswith(test_prefix):
            logger.warning("API key rejected: unrecognized prefix")
            return None

        # In production (non-debug), reject test keys
        if not settings.DEBUG and key.startswith(test_prefix):
            logger.warning("API key rejected: test key used in production")
            return None

        key_hash = APIKeyService.hash_key(key)
        api_key = get_api_key_by_hash(db, key_hash)

        if not api_key:
            return None

        if not api_key.is_active:
            return None

        if is_expired(api_key.expires_at):
            return None

        user = get_user_or_none(db, api_key.user_id)
        organization = get_organization_or_none(db, api_key.organization_id)

        if not user or not organization:
            return None

        if not user.is_active or not organization.is_active:
            return None

        api_key.last_used_at = utcnow()
        db.flush()

        return api_key, user, organization

    @staticmethod
    def revoke_key(db: Session, key_id: str) -> bool:
        """Revoke an API key.

        Args:
            db: Database session
            key_id: Key ID to revoke

        Returns:
            True if revoked, False if not found
        """
        api_key = db.query(APIKey).filter(APIKey.id == key_id).first()

        if not api_key:
            return False

        api_key.is_active = False
        db.commit()

        return True

    @staticmethod
    def list_keys(db: Session, user_id: str, organization_id: str | None = None) -> list[APIKey]:
        """List all API keys for a user, optionally scoped to an organization.

        Args:
            db: Database session
            user_id: User ID
            organization_id: Optional organization ID for multi-tenant filtering

        Returns:
            List of APIKey models
        """
        query = db.query(APIKey).filter(APIKey.user_id == user_id)
        if organization_id:
            query = query.filter(APIKey.organization_id == organization_id)
        return query.all()
