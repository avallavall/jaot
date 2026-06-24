"""Model media upload endpoints (logo, screenshots, sections)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.models import ModelCatalog, User
from app.schemas.model import ModelCatalogResponse, UpdateCatalogSectionsRequest
from app.services.storage_service import get_storage_service
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["model-media"])

# --- Constants ---
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_SCREENSHOTS = 6
LOGO_SIZE = 256  # square resize dimension
SCREENSHOT_MAX_WIDTH = 1920


def _get_catalog_model_for_owner(
    model_id: str,
    current_user: User,
    db: Session,
) -> ModelCatalog:
    """Fetch a catalog model and verify ownership."""
    model = db.query(ModelCatalog).filter(ModelCatalog.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.author_organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this model")
    return model


async def _validate_image(file: UploadFile) -> bytes:
    """Validate content type and size, return raw bytes."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{file.content_type}'. Allowed: JPEG, PNG, WebP.",
        )
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(content)} bytes). Maximum: {MAX_SIZE} bytes (2 MB).",
        )
    return content


def _get_storage():  # noqa: ANN202
    """Get storage service, raise 503 if not configured."""
    try:
        return get_storage_service()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post("/catalog/{model_id}/logo")
async def upload_logo(
    model_id: str,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Upload or replace a model logo image."""
    storage = _get_storage()
    model = _get_catalog_model_for_owner(model_id, current_user, db)
    content = await _validate_image(file)

    if model.logo_url:
        try:
            storage.delete_image(model.logo_url)
        except Exception:
            logger.warning("Failed to delete old logo for model %s", model_id, exc_info=True)

    url = storage.upload_image(
        content,
        "logos",
        max_width=LOGO_SIZE,
        max_height=LOGO_SIZE,
        square_crop=True,
    )

    model.logo_url = url
    db.commit()

    return {"url": url}


@router.delete("/catalog/{model_id}/logo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_logo(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete the model logo image."""
    storage = _get_storage()
    model = _get_catalog_model_for_owner(model_id, current_user, db)

    if model.logo_url:
        try:
            storage.delete_image(model.logo_url)
        except Exception:
            logger.warning(
                "Failed to delete logo from storage for model %s", model_id, exc_info=True
            )

    model.logo_url = None
    db.commit()


@router.post("/catalog/{model_id}/screenshots")
async def upload_screenshot(
    model_id: str,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str | list[str]]:
    """Upload a screenshot image for a model (max 6)."""
    storage = _get_storage()
    model = _get_catalog_model_for_owner(model_id, current_user, db)
    content = await _validate_image(file)

    current_urls: list[str] = model.screenshot_urls or []
    if len(current_urls) >= MAX_SCREENSHOTS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {MAX_SCREENSHOTS} screenshots reached. Delete one before uploading.",
        )

    url = storage.upload_image(content, "screenshots", max_width=SCREENSHOT_MAX_WIDTH)

    updated = [*current_urls, url]
    model.screenshot_urls = updated
    db.commit()

    return {"url": url, "screenshots": model.screenshot_urls}


@router.delete("/catalog/{model_id}/screenshots/{index}")
async def delete_screenshot(
    model_id: str,
    index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[str]]:
    """Delete a screenshot by index (0-based)."""
    storage = _get_storage()
    model = _get_catalog_model_for_owner(model_id, current_user, db)

    current_urls: list[str] = model.screenshot_urls or []
    if index < 0 or index >= len(current_urls):
        raise HTTPException(status_code=400, detail=f"Invalid screenshot index {index}")

    url_to_delete = current_urls[index]
    try:
        storage.delete_image(url_to_delete)
    except Exception:
        logger.warning("Failed to delete screenshot from storage: %s", url_to_delete, exc_info=True)

    updated = [u for i, u in enumerate(current_urls) if i != index]
    model.screenshot_urls = updated if updated else None
    db.commit()

    return {"screenshots": model.screenshot_urls or []}


@router.put("/catalog/{model_id}/sections", response_model=ModelCatalogResponse)
async def update_sections(
    model_id: str,
    body: UpdateCatalogSectionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelCatalogResponse:
    """Update rich description sections on a published model."""
    model = _get_catalog_model_for_owner(model_id, current_user, db)

    # Only update fields that were explicitly provided (not None)
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(model, field, value)

    db.commit()
    db.refresh(model)

    return ModelCatalogResponse.model_validate(model)
