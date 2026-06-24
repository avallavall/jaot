"""Object storage service for Cloudflare R2 (S3-compatible).

Handles image upload with automatic resizing, WebP conversion,
and metadata stripping. Used for model logos and screenshots.
"""

import io
import logging
from typing import Any
from uuid import uuid4

import boto3
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class StorageService:
    """S3-compatible object storage client for Cloudflare R2."""

    def __init__(
        self,
        account_id: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        cdn_url: str,
    ) -> None:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        self._bucket = bucket
        self._cdn_url = cdn_url.rstrip("/")

    def upload_image(
        self,
        file_bytes: bytes,
        folder: str,
        *,
        max_width: int = 1920,
        max_height: int = 1080,
        square_crop: bool = False,
    ) -> str:
        """Upload an image after resizing and converting to WebP.

        Args:
            file_bytes: Raw image bytes.
            folder: Storage folder (e.g. "logos", "screenshots").
            max_width: Maximum output width.
            max_height: Maximum output height.
            square_crop: If True, center-crop to square before resizing.

        Returns:
            CDN URL of the uploaded image.
        """
        img = Image.open(io.BytesIO(file_bytes))
        # Fix orientation from EXIF data (critical for phone photos)
        img = ImageOps.exif_transpose(img)

        if square_crop:
            # Center-crop to square
            min_dim = min(img.width, img.height)
            left = (img.width - min_dim) // 2
            top = (img.height - min_dim) // 2
            img = img.crop((left, top, left + min_dim, top + min_dim))
            img = img.resize((max_width, max_width), Image.LANCZOS)
        else:
            img.thumbnail((max_width, max_height), Image.LANCZOS)

        # Convert to RGB if necessary (e.g. RGBA, P mode)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Save as WebP -- do NOT copy info dict (strips metadata)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=85)
        buf.seek(0)

        key = f"{folder}/{uuid4().hex}.webp"
        self._client.upload_fileobj(
            buf,
            self._bucket,
            key,
            ExtraArgs={"ContentType": "image/webp"},
        )

        return f"{self._cdn_url}/{key}"

    def delete_image(self, url: str) -> None:
        """Delete an image from storage by its CDN URL."""
        if not url or not self._cdn_url:
            return
        key = url.removeprefix(self._cdn_url).lstrip("/")
        if not key:
            return
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.info("Deleted image: %s", key)


def get_storage_service(
    db: Any | None = None,
) -> "StorageService":
    """Return a StorageService instance.

    Reads storage credentials from ``platform_settings`` DB table.
    Raises RuntimeError if R2 storage is not configured.
    """
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )

    if db is None:
        from app.shared.db.session import SessionLocal

        db = SessionLocal()
        _close = True
    else:
        _close = False

    try:
        account_id = PSS.get_str(db, "STORAGE_ACCOUNT_ID")
        if not account_id:
            raise RuntimeError(
                "Object storage is not configured. "
                "Set STORAGE_ACCOUNT_ID, STORAGE_ACCESS_KEY, "
                "STORAGE_SECRET_KEY, and STORAGE_CDN_URL "
                "via the admin panel."
            )
        return StorageService(
            account_id=account_id,
            access_key=PSS.get_str(db, "STORAGE_ACCESS_KEY"),
            secret_key=PSS.get_str(db, "STORAGE_SECRET_KEY"),
            bucket=PSS.get_str(db, "STORAGE_BUCKET"),
            cdn_url=PSS.get_str(db, "STORAGE_CDN_URL"),
        )
    finally:
        if _close:
            db.close()
