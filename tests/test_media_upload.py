"""Logo / screenshot upload for a marketplace listing.

These handlers had NO upload coverage — only their delete counterparts were tested —
which came to light when ADR-009 made them sync `def` (they push to object storage
through boto3, i.e. blocking network I/O that has no business on the event loop) and
`_validate_image` had to read the already-spooled multipart file directly instead of
awaiting it. That read is the thing under test here.

Object storage is a third-party service and is faked; the database and auth are real,
per the project's testing rules.
"""

import base64

import pytest
from sqlalchemy.orm import Session

from app.api.v2.routes.models import media as media_module
from app.models import ModelProject, ModelProjectListing
from app.shared.utils.id_generator import generate_id

# A real 1x1 PNG. The bytes that were here before were hand-assembled and their
# IDAT checksum did not match, so Pillow refuses them ("broken PNG file"). That
# went unnoticed while nothing checked whether an upload was really an image;
# the moment `_validate_image` started checking, the fixture was a file the
# platform correctly rejects.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
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


class TestTheBytesMustBeAnImage:
    """The declared type is whatever the client wrote in the multipart header.

    Found by driving the marketplace (QA sweep, 2026-08-20): the first check
    reads that header, so a text file called ``logo.png`` passed it and Pillow
    raised inside the storage service — reaching the author as a 500.
    """

    @pytest.mark.parametrize(
        ("what", "payload"),
        [
            ("plain text", b"this is not an image at all"),
            ("html", b"<html><script>alert(1)</script></html>"),
            ("an empty file", b""),
            ("a truncated PNG", PNG_BYTES[:12]),
        ],
    )
    def test_a_file_that_is_not_an_image_is_refused_with_a_message(
        self, authenticated_client, owned_listing, fake_storage, what, payload
    ):
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/logo",
            files={"file": ("logo.png", payload, "image/png")},
        )

        assert resp.status_code == 400, f"{what}: {resp.status_code} {resp.text}"
        assert "not a readable image" in resp.json()["detail"]
        assert not fake_storage.uploaded

    def test_the_same_guard_covers_screenshots(
        self, authenticated_client, owned_listing, fake_storage
    ):
        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/screenshots",
            files={"file": ("shot.png", b"still not an image", "image/png")},
        )

        assert resp.status_code == 400, resp.text
        assert not fake_storage.uploaded


class TestUploadsWithoutStorage:
    """An instance with no object storage says what that means for the author."""

    def test_the_refusal_does_not_hand_the_author_the_operator_s_instructions(
        self, authenticated_client, owned_listing, monkeypatch
    ):
        def _unconfigured(*_a, **_kw):
            raise RuntimeError(
                "Object storage is not configured. Set STORAGE_ACCOUNT_ID, "
                "STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY, and STORAGE_CDN_URL "
                "via the admin panel."
            )

        monkeypatch.setattr(media_module, "get_storage_service", _unconfigured)

        resp = authenticated_client.post(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/logo",
            files={"file": ("logo.png", PNG_BYTES, "image/png")},
        )

        assert resp.status_code == 503, resp.text
        body = resp.json()
        assert "STORAGE_" not in body["detail"], "the author is handed settings names"
        # CONTRACT-TEST: the page has to tell this apart from a rejected file, so
        # the refusal names itself.
        assert body["code"] == "listing.image_storage_off"


class TestSectionsRequest:
    """A wrong field name must be a 422, and a section has a ceiling."""

    def test_a_body_with_no_known_field_is_refused(self, authenticated_client, owned_listing):
        # `{"sections": {...}}` answered 200 with the listing unchanged, so a
        # client with the wrong shape believed it had saved.
        resp = authenticated_client.put(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/sections",
            json={"sections": {"overview": "nope"}},
        )
        assert resp.status_code == 422, resp.text

    def test_a_section_longer_than_the_cap_is_refused(
        self, authenticated_client, db_session, owned_listing
    ):
        from app.schemas.model import MAX_SECTION_CHARS

        resp = authenticated_client.put(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/sections",
            json={"section_overview": "x" * (MAX_SECTION_CHARS + 1)},
        )
        assert resp.status_code == 422, resp.text
        db_session.refresh(owned_listing)
        assert owned_listing.section_overview is None

    def test_a_section_within_the_cap_is_stored(
        self, authenticated_client, db_session, owned_listing
    ):
        resp = authenticated_client.put(
            f"/api/v2/models/catalog/{owned_listing.model_project_id}/sections",
            json={"section_overview": "## Overview\nWhat this model does."},
        )
        assert resp.status_code == 200, resp.text
        db_session.refresh(owned_listing)
        assert owned_listing.section_overview.startswith("## Overview")
