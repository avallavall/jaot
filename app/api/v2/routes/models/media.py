"""Listing media upload endpoints (logo, screenshots, sections).

P1.5 fusion: media lives on the ``ModelProjectListing`` facet (the marketplace
presentation of a ModelProject). Routes keep their historic ``/catalog/{id}``
shape — the id IS the project id.
"""

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.api.deps import DBSession
from app.api.v2.auth import get_current_user
from app.models import ModelProjectListing, User
from app.schemas.model import (
    LogoUploadResponse,
    ModelCatalogResponse,
    ScreenshotListResponse,
    ScreenshotUploadResponse,
    UpdateCatalogSectionsRequest,
)
from app.services.author_analytics_service import adoption_count
from app.services.marketplace_fusion import listing_to_catalog_response
from app.services.storage_service import get_storage_service
from app.shared.core.http_errors import CodedHTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["model-media"])

# --- Constants ---
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_SCREENSHOTS = 6
LOGO_SIZE = 256  # square resize dimension
SCREENSHOT_MAX_WIDTH = 1920


def _get_listing_for_owner(
    model_id: str,
    current_user: User,
    db: Session,
) -> ModelProjectListing:
    """Fetch a marketplace listing and verify author-org ownership."""
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == model_id)
        .first()
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Model not found")
    if listing.author_organization_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this model")
    return listing


def _validate_image(file: UploadFile) -> bytes:
    """Validate type, size and the bytes themselves, and return them.

    Sync so its callers can be sync ``def`` handlers (ADR-009): they upload to object
    storage through boto3, which is blocking network I/O, and on the event loop that
    stalled every other request for the duration of the upload. Reading the
    already-spooled multipart file directly is safe — Starlette buffers the upload
    before the handler runs.

    Three checks, in the order that costs least:

    * the type the client declared, which is the cheapest thing to refuse;
    * the size, read from the spooled part BEFORE pulling it into memory — the
      length used to be measured on bytes already read, so a 200 MB upload was
      held in RAM only to be refused;
    * the bytes really being an image. The declared type is whatever the client
      wrote in the multipart header. A text file called ``logo.png`` passed the
      first check, and Pillow raised on it inside the storage service, which
      reached the author as a 500.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{file.content_type}'. Allowed: JPEG, PNG, WebP.",
        )

    declared = file.size
    if declared is not None and declared > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({declared} bytes). Maximum: {MAX_SIZE} bytes (2 MB).",
        )

    content = file.file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(content)} bytes). Maximum: {MAX_SIZE} bytes (2 MB).",
        )

    try:
        with PILImage.open(io.BytesIO(content)) as probe:
            probe.verify()
    except Exception as exc:  # noqa: BLE001 — Pillow raises many types for bad input
        logger.info("Rejected an upload that is not a readable image: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=(
                "This file is not a readable image, whatever its name says it is. "
                "Send a JPEG, a PNG or a WebP."
            ),
        ) from exc

    return content


def _get_storage():  # noqa: ANN202
    """Get storage service, raise 503 if not configured.

    The service's own message is written for whoever runs the instance: it names
    the four settings to fill in. It used to be handed to the author uploading a
    logo, who can do nothing with it. It goes to the log; the author is told what
    it means for them.
    """
    try:
        return get_storage_service()
    except RuntimeError as exc:
        logger.warning("Image upload refused: %s", exc)
        raise CodedHTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This instance cannot store images yet, so logos and screenshots "
                "are unavailable. Everything else about your listing works. Ask "
                "whoever runs it to set up image storage."
            ),
            code="listing.image_storage_off",
        ) from exc


@router.post("/catalog/{model_id}/logo", response_model=LogoUploadResponse)
def upload_logo(  # sync ON PURPOSE -> threadpool (ADR-009): boto3 upload blocks
    model_id: str,
    file: UploadFile,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> LogoUploadResponse:
    """Upload or replace a model logo image."""
    storage = _get_storage()
    model = _get_listing_for_owner(model_id, current_user, db)
    content = _validate_image(file)

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

    return LogoUploadResponse(url=url)


@router.delete("/catalog/{model_id}/logo", status_code=status.HTTP_204_NO_CONTENT)
def delete_logo(
    model_id: str,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete the model logo image."""
    storage = _get_storage()
    model = _get_listing_for_owner(model_id, current_user, db)

    if model.logo_url:
        try:
            storage.delete_image(model.logo_url)
        except Exception:
            logger.warning(
                "Failed to delete logo from storage for model %s", model_id, exc_info=True
            )

    model.logo_url = None
    db.commit()


@router.post("/catalog/{model_id}/screenshots", response_model=ScreenshotUploadResponse)
def upload_screenshot(  # sync ON PURPOSE -> threadpool (ADR-009): boto3 upload blocks
    model_id: str,
    file: UploadFile,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> ScreenshotUploadResponse:
    """Upload a screenshot image for a model (max 6)."""
    storage = _get_storage()
    model = _get_listing_for_owner(model_id, current_user, db)
    content = _validate_image(file)

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

    return ScreenshotUploadResponse(url=url, screenshots=model.screenshot_urls)


@router.delete("/catalog/{model_id}/screenshots/{index}", response_model=ScreenshotListResponse)
def delete_screenshot(
    model_id: str,
    index: int,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> ScreenshotListResponse:
    """Delete a screenshot by index (0-based)."""
    storage = _get_storage()
    model = _get_listing_for_owner(model_id, current_user, db)

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

    return ScreenshotListResponse(screenshots=model.screenshot_urls or [])


@router.put("/catalog/{model_id}/sections", response_model=ModelCatalogResponse)
def update_sections(
    model_id: str,
    body: UpdateCatalogSectionsRequest,
    db: DBSession,
    current_user: User = Depends(get_current_user),
) -> ModelCatalogResponse:
    """Update rich description sections on a published model."""
    model = _get_listing_for_owner(model_id, current_user, db)

    # Only update fields that were explicitly provided (not None)
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(model, field, value)

    db.commit()
    db.refresh(model)

    return listing_to_catalog_response(
        model, total_activations=adoption_count(db, model.model_project_id)
    )
