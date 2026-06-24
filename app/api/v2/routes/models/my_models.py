"""Organization model management endpoints."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, OrganizationModel, User
from app.schemas.model import (
    CreatePrivateModelRequest,
    OrganizationModelListResponse,
    OrganizationModelResponse,
    UpdateModelRequest,
)
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.model_helpers import build_org_model_response
from app.shared.utils.pagination import paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["my-models"])


@router.get("/", response_model=OrganizationModelListResponse)
async def list_my_models(
    category: str | None = Query(None),
    is_active: bool | None = Query(None),
    is_favorite: bool | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationModelListResponse:
    """List models belonging to the user's organization."""
    query = db.query(OrganizationModel).filter(
        OrganizationModel.organization_id == current_user.organization_id,
    )

    if is_active is not None:
        query = query.filter(OrganizationModel.is_active == is_active)

    if is_favorite is not None:
        query = query.filter(OrganizationModel.is_favorite == is_favorite)

    if category or search:
        query = query.outerjoin(ModelCatalog, OrganizationModel.catalog_id == ModelCatalog.id)

        if category:
            query = query.filter(ModelCatalog.category == category)

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    OrganizationModel.custom_name.ilike(search_term),
                    ModelCatalog.name.ilike(search_term),
                    ModelCatalog.display_name.ilike(search_term),
                )
            )

    query = query.order_by(
        OrganizationModel.last_executed_at.desc().nullslast(), OrganizationModel.created_at.desc()
    )

    models, total = paginate_query(query, page, page_size)

    return OrganizationModelListResponse(
        items=[build_org_model_response(s) for s in models],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{model_id}", response_model=OrganizationModelResponse)
async def get_my_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationModelResponse:
    """Get details of a specific organization model."""
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

    return build_org_model_response(model)


@router.get("/{model_id}/schema")
async def get_my_model_schema(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get the input schema and example for executing a model."""
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

    if model.catalog_model:
        return {
            "id": model.id,
            "name": model.custom_name or model.catalog_model.display_name,
            "generator_type": model.catalog_model.generator_type,
            "input_schema": model.catalog_model.input_schema,
            "input_fields": model.catalog_model.input_fields,
            "example_input": model.catalog_model.example_input,
            "custom_config": model.custom_config,
        }
    elif model.private_definition:
        return {
            "id": model.id,
            "name": model.custom_name or model.private_definition.get("name"),
            "generator_type": model.private_definition.get("generator_type"),
            "input_schema": model.private_definition.get("input_schema", {}),
            "input_fields": model.private_definition.get("input_fields", []),
            "example_input": model.private_definition.get("example_input", {}),
            "custom_config": model.custom_config,
        }
    else:
        raise HTTPException(status_code=500, detail="Model has no definition")


@router.post("/", response_model=OrganizationModelResponse)
async def create_private_model(
    body: CreatePrivateModelRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganizationModelResponse:
    """Create a private model for the organization."""
    private_definition = {
        "name": body.name,
        "description": body.description,
        "category": body.category,
        "generator_type": body.generator_type,
        "input_schema": body.input_schema,
        "input_fields": body.input_fields,
        "example_input": body.example_input,
        "tags": body.tags or [],
    }

    model = OrganizationModel(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        catalog_id=None,
        custom_name=body.name,
        private_definition=private_definition,
        is_active=True,
    )

    db.add(model)
    db.commit()
    db.refresh(model)

    # Fire-and-forget: log model.create analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=current_user.id,
            org_id=current_user.organization_id,
            event_type=evt.MODEL_CREATE,
            ip_address=request.client.host if request.client else None,
            metadata={"model_name": model.custom_name},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    return build_org_model_response(model)


@router.patch("/{model_id}")
async def update_my_model(
    model_id: str,
    body: UpdateModelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a model's custom settings."""
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

    if body.custom_name is not None:
        model.custom_name = body.custom_name
    if body.custom_config is not None:
        model.custom_config = body.custom_config
    if body.is_active is not None:
        model.is_active = body.is_active
    if body.is_favorite is not None:
        model.is_favorite = body.is_favorite

    model.updated_at = utcnow()
    db.commit()

    return {"status": "updated"}


@router.delete("/{model_id}")
async def deactivate_my_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Deactivate (soft delete) a model."""
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

    model.is_active = False
    model.updated_at = utcnow()
    db.commit()

    return {"status": "deactivated"}
