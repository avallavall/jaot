"""Model response builder helpers.

Shared utilities for building model responses across API endpoints.
"""

from typing import Any, cast

from app.models import OrganizationModel
from app.schemas.model import OrganizationModelResponse


def build_org_model_response(model: OrganizationModel) -> OrganizationModelResponse:
    """Build OrganizationModelResponse from an OrganizationModel.

    Handles three cases:
    1. Model linked to catalog (has catalog_model)
    2. Private model (has private_definition)
    3. Fallback for edge cases

    Args:
        model: OrganizationModel instance

    Returns:
        OrganizationModelResponse with all fields populated
    """
    if model.catalog_model:
        cat = model.catalog_model
        return OrganizationModelResponse(
            id=model.id,
            organization_id=model.organization_id,
            catalog_id=model.catalog_id,
            custom_name=model.custom_name,
            display_name=model.custom_name or cat.display_name,
            description=cat.description,
            category=cat.category,
            generator_type=cat.generator_type,
            is_active=model.is_active,
            is_favorite=model.is_favorite,
            total_executions=model.total_executions,
            total_credits_used=model.total_credits_used,
            last_executed_at=model.last_executed_at,
            credits_per_execution=cat.credits_per_execution,
            created_at=model.created_at,
            is_official=cat.is_official,
            tags=cast(Any, cat.tags),
        )

    if model.private_definition:
        priv = model.private_definition
        return OrganizationModelResponse(
            id=model.id,
            organization_id=model.organization_id,
            catalog_id=None,
            custom_name=model.custom_name,
            display_name=model.custom_name or priv.get("name", "Custom Model"),
            description=priv.get("description"),
            category=priv.get("category", "general"),
            generator_type=priv.get("generator_type"),
            is_active=model.is_active,
            is_favorite=model.is_favorite,
            total_executions=model.total_executions,
            total_credits_used=model.total_credits_used,
            last_executed_at=model.last_executed_at,
            credits_per_execution=1,
            created_at=model.created_at,
            is_official=False,
            tags=priv.get("tags"),
        )

    # Fallback for edge cases
    return OrganizationModelResponse(
        id=model.id,
        organization_id=model.organization_id,
        catalog_id=model.catalog_id,
        custom_name=model.custom_name,
        display_name=model.custom_name or "Unknown Model",
        description=None,
        category="general",
        generator_type=None,
        is_active=model.is_active,
        is_favorite=model.is_favorite,
        total_executions=model.total_executions,
        total_credits_used=model.total_credits_used,
        last_executed_at=model.last_executed_at,
        credits_per_execution=1,
        created_at=model.created_at,
        is_official=False,
        tags=None,
    )
