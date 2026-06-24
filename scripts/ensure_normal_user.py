#!/usr/bin/env python3
"""Ensure a normal (member) user exists and print a fresh API key."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Inject scripts/ onto sys.path so ``_seed_common`` is importable when invoked
# as ``python scripts/ensure_normal_user.py`` without pip-install.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _seed_common import (  # noqa: E402  — path injection must happen first
    add_repo_to_path,
    get_or_create_user,
    resolve_id_prefixes,
    session_scope,
)

add_repo_to_path()

USER_EMAIL = os.getenv("ENSURE_USER_EMAIL", "user@jaot.io")
USER_NAME = os.getenv("ENSURE_USER_NAME", "Demo User")
USER_PASSWORD = os.getenv("ENSURE_USER_PASSWORD", "DemoPass123!")
USER_KEY_NAME = os.getenv("ENSURE_USER_KEY_NAME", "Demo User Key")
USER_KEY_PREFIX = os.getenv("ENSURE_USER_KEY_PREFIX") or None  # resolved via PSS in main()
ORG_NAME = os.getenv("ENSURE_USER_ORG_NAME", "Primary Organization")


def main() -> None:
    from app.models import Organization
    from app.services.auth import APIKeyService

    with session_scope() as db:
        prefixes = resolve_id_prefixes(db)

        org = db.query(Organization).filter(Organization.name == ORG_NAME).first()
        if not org:
            print(f"ERROR: Organization '{ORG_NAME}' not found. Run ensure_admin_api_key.py first.")
            sys.exit(1)

        user, user_created = get_or_create_user(
            db,
            email=USER_EMAIL,
            name=USER_NAME,
            password=USER_PASSWORD,
            organization_id=org.id,
            role="member",
            prefix=prefixes["ID_PREFIX_USER"],
        )

        # Dev-only convenience: mark the seeded user as org owner so E2E
        # flows that require OrgOwnerUser work without hand-patching the DB.
        # Idempotent — leave existing owner alone.
        if user_created and not org.owner_user_id:
            org.owner_user_id = user.id
            db.commit()

        key_prefix = USER_KEY_PREFIX or prefixes["API_KEY_DEFAULT_PREFIX"]
        _, plaintext = APIKeyService.create_api_key(
            db=db,
            user_id=user.id,
            organization_id=org.id,
            name=USER_KEY_NAME,
            prefix=key_prefix,
        )

        print("----------------------------------------")
        print("Normal user provisioning summary")
        print("----------------------------------------")
        print(f"Organization: {org.name} ({org.id})")
        print(f"User: {user.email} ({user.id}){' [created]' if user_created else ''}")
        print(f"Role: {user.role}")
        print(f"Password: {USER_PASSWORD}")
        print(f"API key name: {USER_KEY_NAME}")
        print("API key (copy now, only shown once):")
        print(plaintext)
        print("----------------------------------------")


if __name__ == "__main__":
    main()
