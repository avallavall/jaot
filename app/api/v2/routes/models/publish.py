"""Model publishing endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, Organization, OrganizationModel, User
from app.schemas.model import ModelCatalogResponse, PublishModelRequest
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publish"])


@router.post("/{model_id}/publish", response_model=ModelCatalogResponse)
async def publish_model_to_marketplace(
    model_id: str,
    body: PublishModelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Publish a private model to the marketplace."""
    model = (
        db.query(OrganizationModel)
        .filter(
            OrganizationModel.id == model_id,
            OrganizationModel.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if model.catalog_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot publish a model from the catalog. Only private models can be published.",
        )

    if not model.private_definition:
        raise HTTPException(
            status_code=400, detail="Model has no definition. Create a valid model first."
        )

    private_def = model.private_definition

    catalog_id = str(uuid.uuid4())
    catalog_model = ModelCatalog(
        id=catalog_id,
        name=body.display_name.lower().replace(" ", "_"),
        display_name=body.display_name,
        description=body.description,
        short_description=body.short_description,
        category=body.category,
        tags=body.tags,
        generator_type=private_def.get("generator_type", "custom"),
        input_schema=private_def.get("input_schema", {}),
        input_fields=private_def.get("input_fields", []),
        example_input=private_def.get("example_input", {}),
        version="1.0.0",
        status="published",
        author_organization_id=current_user.organization_id,
        is_official=False,
        price_eur=body.price_eur,
        credits_per_execution=1,  # Ignored for billing; credits calculated dynamically
        is_public=True,
        published_at=utcnow(),
        # Rich description sections
        section_overview=body.section_overview,
        section_features=body.section_features,
        section_how_it_works=body.section_how_it_works,
        section_example_io=body.section_example_io,
        section_changelog=body.section_changelog,
    )

    db.add(catalog_model)

    model.catalog_id = catalog_id
    model.updated_at = utcnow()

    db.commit()
    db.refresh(catalog_model)

    response = ModelCatalogResponse.model_validate(catalog_model)
    author_org = (
        db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    )
    if author_org:
        response.author_name = author_org.name

    # Fire-and-forget: log marketplace.publish analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=current_user.id,
            org_id=current_user.organization_id,
            event_type=evt.MARKETPLACE_PUBLISH,
            ip_address=request.client.host if request.client else None,
            metadata={"catalog_id": catalog_model.id},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    return response
