"""Logo / screenshot upload for a marketplace listing.

These handlers had NO upload coverage — only their delete counterparts were tested —
which came to light when ADR-009 made them sync `def` (they push to object storage
through boto3, i.e. blocking network I/O that has no business on the event loop) and
`_validate_image` had to read the already-spooled multipart file directly instead of
awaiting it. That read is the thing under test here.

Object storage is a third-party service and is faked; the database and auth are real,
per the project's testing rules.
"""

import pytest
from sqlalchemy.orm import Session

from app.api.v2.routes.models import media as media_module
from app.models import ModelProject, ModelProjectListing
from app.shared.utils.id_generator import generate_id

# Smallest possible real PNG: signature + IHDR-onwards bytes of a 1x1 image.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0000003010100189dd4ca0000000049454e44ae426082"
)


class _FakeStorage:
    """Stands in for the object-storage service (boto3/R2)."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[bytes, str]] = []
        self.deleted: list[str] = []

    def upload_image(self, file_bytes: bytes, folder: str, **kwargs) -> str:  # noqa: ANN003
        self.uploaded.append((file_bytes, folder))
        return "https://cdn.example.test/img.png"

    def delete_image(self, url: str) -> None:
        self.deleted.append(url)


@pytest.fixture
def fake_storage(monkeypatch) -> _FakeStorage:
    storage = _FakeStorage()
    monkeypatch.setattr(media_module, "get_storage_service", lambda *a, **kw: storage)
    return storage


@pytest.fixture
def owned_listing(db_session: Session, test_organization) -> ModelProjectListing:
    """A published listing owned by the authenticated client's organization."""
    pid = generate_id("mp_")
    db_session.add(
        ModelProject(
            id=pid, organization_id=test_organization.id, name="Media Source", status="active"
        )
    )
    db_session.flush()
    listing = ModelProjectListing(
        model_project_id=pid,
        name="media_upload_model",
        display_name="Media Upload Model",
        description="Listing used by the media upload tests",
        category="general",
        generator_type="custom",
        input_schema={"type": "object"},
        input_fields=[{"name": "x", "type": "number"}],
        example_input={"x": 1},
        status="published",
        is_public=True,
        author_organization_id=test_organization.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)
    return listing


class TestLogoUpload:
    """# CONTRACT-TEST: the sync handler reads the spooled upload correctly."""

    def test_logo_upload_stores_the_real_bytes(
        self, authenticated_client, owned_listing, fake_storage
    ):
        """The bytes that reach storage are the ones that were uploaded."""
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/logo",
            files={"file": ("logo.png", PNG_BYTES, "image/png")},
        )

        assert resp.status_code == 200, resp.text
        assert fake_storage.uploaded, "the handler never reached storage"
        sent, _folder = fake_storage.uploaded[0]
        # The whole point: a sync read of the spooled file yields the full body, not
        # an empty buffer or a coroutine.
        assert sent == PNG_BYTES

    def test_rejects_a_non_image_type(self, authenticated_client, owned_listing, fake_storage):
        """A non-image content type is refused before anything is stored."""
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/logo",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

        assert resp.status_code == 400
        assert not fake_storage.uploaded

    def test_rejects_an_oversized_image(self, authenticated_client, owned_listing, fake_storage):
        """Over the 2 MB cap is refused, and the size check saw the real length."""
        oversized = PNG_BYTES + b"\x00" * (media_module.MAX_SIZE + 1)
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/logo",
            files={"file": ("huge.png", oversized, "image/png")},
        )

        assert resp.status_code == 400
        assert not fake_storage.uploaded


class TestScreenshotUpload:
    """The screenshot handler shares `_validate_image`, so cover its read too."""

    def test_screenshot_upload_stores_the_real_bytes(
        self, authenticated_client, owned_listing, fake_storage
    ):
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/screenshots",
            files={"file": ("shot.png", PNG_BYTES, "image/png")},
        )

        assert resp.status_code in (200, 201), resp.text
        assert fake_storage.uploaded
        sent, _folder = fake_storage.uploaded[0]
        assert sent == PNG_BYTES
