"""
Tests for Favorites and Recents API (P1.5 fusion: keyed on model_project_id).

These tests verify the favorites/recents functionality:
- Adding/removing favorites
- Listing favorites
- Getting favorite status
"""

from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.models import (
    ModelCategory,
    ModelProject,
    ModelProjectListing,
    Organization,
    RecentModel,
    UserFavorite,
)
from app.services import favorites_service
from app.shared.core import auth_middleware
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _project(db, org, *, pid) -> None:
    """A ModelProject with no marketplace listing facet."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.commit()


def _listing(db, org, *, pid) -> None:
    """A published ModelProject + its marketplace listing facet."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="A model for favorites tests",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
        )
    )
    db.commit()


class TestFavoritesList:
    """Tests for GET /api/v2/models/favorites"""

    def test_list_favorites_with_favorites(
        self, authenticated_client, db_session, test_organization
    ):
        """Test listing favorites by adding one first."""
        _listing(db_session, test_organization, pid="test_fav_model")

        add_response = authenticated_client.post("/api/v2/models/favorites/test_fav_model")
        assert add_response.status_code == 200

        response = authenticated_client.get("/api/v2/models/favorites")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_fav_model" in model_ids


class TestFavoriteAuthor:
    """Author attribution on the favorites list (P1.5 fusion).

    Backfilled/legacy listings carry no ``author_organization_id`` (the legacy
    catalog never did) — the author must resolve through the owning project's
    organization instead of rendering "Unknown".
    """

    def test_author_falls_back_to_project_org(
        self, authenticated_client, db_session, test_organization
    ):
        _listing(db_session, test_organization, pid="test_fav_author_fallback")

        assert (
            authenticated_client.post(
                "/api/v2/models/favorites/test_fav_author_fallback"
            ).status_code
            == 200
        )

        data = authenticated_client.get("/api/v2/models/favorites").json()
        item = next(i for i in data["items"] if i["id"] == "test_fav_author_fallback")
        assert item["author_name"] == test_organization.name

    def test_author_from_listing_when_present(
        self, authenticated_client, db_session, test_organization
    ):
        """An explicit listing author (the fused publish path sets it) wins."""
        author_org = Organization(id=generate_id("org_"), name="Listing Author Org")
        db_session.add(author_org)
        _listing(db_session, test_organization, pid="test_fav_author_explicit")
        listing = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == "test_fav_author_explicit")
            .one()
        )
        listing.author_organization_id = author_org.id
        db_session.commit()

        assert (
            authenticated_client.post(
                "/api/v2/models/favorites/test_fav_author_explicit"
            ).status_code
            == 200
        )

        data = authenticated_client.get("/api/v2/models/favorites").json()
        item = next(i for i in data["items"] if i["id"] == "test_fav_author_explicit")
        assert item["author_name"] == "Listing Author Org"


class TestAddFavorite:
    """Tests for POST /api/v2/models/favorites/{model_id}"""

    def test_add_favorite(self, authenticated_client, db_session, test_user, test_organization):
        """Test adding a model to favorites."""
        _listing(db_session, test_organization, pid="test_add_fav_model")

        response = authenticated_client.post("/api/v2/models/favorites/test_add_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_add_fav_model"
        assert data["is_favorite"]

        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_add_fav_model",
            )
            .first()
        )
        assert favorite is not None

    def test_add_favorite_already_favorited(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """Test adding already favorited model is idempotent (no duplicate row)."""
        _listing(db_session, test_organization, pid="test_already_fav_model")
        db_session.add(
            UserFavorite(user_id=test_user.id, model_project_id="test_already_fav_model")
        )
        db_session.commit()

        response = authenticated_client.post("/api/v2/models/favorites/test_already_fav_model")
        assert response.status_code == 200
        assert response.json()["is_favorite"]

        count = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_already_fav_model",
            )
            .count()
        )
        assert count == 1

    def test_add_favorite_nonexistent_model(self, authenticated_client):
        """Test adding non-existent model to favorites returns 404."""
        response = authenticated_client.post("/api/v2/models/favorites/nonexistent_model")
        assert response.status_code == 404


class TestRemoveFavorite:
    """Tests for DELETE /api/v2/models/favorites/{model_id}"""

    def test_remove_favorite(self, authenticated_client, db_session, test_user, test_organization):
        """Test removing a model from favorites."""
        _listing(db_session, test_organization, pid="test_remove_fav_model")
        db_session.add(UserFavorite(user_id=test_user.id, model_project_id="test_remove_fav_model"))
        db_session.commit()

        response = authenticated_client.delete("/api/v2/models/favorites/test_remove_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_remove_fav_model"
        assert not data["is_favorite"]

        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_remove_fav_model",
            )
            .first()
        )
        assert favorite is None

    def test_remove_favorite_not_favorited(self, authenticated_client, db_session, test_user):
        """Test removing non-favorited model is idempotent (no row left behind)."""
        response = authenticated_client.delete("/api/v2/models/favorites/some_model")
        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "some_model"
        assert data["is_favorite"] is False
        assert (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "some_model",
            )
            .count()
            == 0
        )


class TestFavoriteStatus:
    """Tests for GET /api/v2/models/favorites/{model_id}/status"""

    def test_get_favorite_status_true(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """Test getting favorite status when favorited."""
        _listing(db_session, test_organization, pid="test_status_fav_model")
        db_session.add(UserFavorite(user_id=test_user.id, model_project_id="test_status_fav_model"))
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/favorites/test_status_fav_model/status")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_status_fav_model"
        assert data["is_favorite"]

    def test_get_favorite_status_false(self, authenticated_client, db_session):
        """Test getting favorite status when not favorited."""
        response = authenticated_client.get("/api/v2/models/favorites/some_model/status")
        assert response.status_code == 200
        data = response.json()
        assert not data["is_favorite"]


def _recent(db, user, *, pid, minutes_ago: int = 0, count: str = "1") -> None:
    """A row in this user's recently-opened list."""
    db.add(
        RecentModel(
            user_id=user.id,
            model_project_id=pid,
            last_accessed=utcnow() - timedelta(minutes=minutes_ago),
            access_count=count,
        )
    )
    db.commit()


class TestRecents:
    """Tests for GET /api/v2/models/recents"""

    def test_recents_empty(self, authenticated_client):
        """A user who has opened nothing gets an empty list, not an error."""
        response = authenticated_client.get("/api/v2/models/recents")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    def test_recents_are_newest_first(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """The list is ordered by when each model was last opened."""
        _listing(db_session, test_organization, pid="test_recent_older")
        _listing(db_session, test_organization, pid="test_recent_newer")
        _recent(db_session, test_user, pid="test_recent_older", minutes_ago=30)
        _recent(db_session, test_user, pid="test_recent_newer", minutes_ago=1)

        data = authenticated_client.get("/api/v2/models/recents").json()
        assert [i["id"] for i in data["items"]] == ["test_recent_newer", "test_recent_older"]
        assert data["total"] == 2

    def test_access_count_is_a_number(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """``access_count`` reaches the client as a number.

        The column is a ``String``, so the route used to hand the raw ORM value
        straight out and the count arrived quoted — while the page that renders
        it declares a number and feeds it to a plural rule, which cannot count a
        string. The response schema is what converts it now.
        """
        _listing(db_session, test_organization, pid="test_recent_count")
        _recent(db_session, test_user, pid="test_recent_count", count="7")

        item = authenticated_client.get("/api/v2/models/recents").json()["items"][0]
        assert item["access_count"] == 7
        assert isinstance(item["access_count"], int)

    def test_recent_without_a_listing_drops_out(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """A model that left the marketplace disappears from the list quietly.

        Recents point at projects, and a project can lose its listing facet
        (unpublished, or never published). That entry has no card to render, so
        it is skipped — it must not blank the whole list or 500 the request.
        """
        _listing(db_session, test_organization, pid="test_recent_listed")
        _project(db_session, test_organization, pid="test_recent_unlisted")
        _recent(db_session, test_user, pid="test_recent_unlisted", minutes_ago=1)
        _recent(db_session, test_user, pid="test_recent_listed", minutes_ago=5)

        response = authenticated_client.get("/api/v2/models/recents")
        assert response.status_code == 200
        data = response.json()
        assert [i["id"] for i in data["items"]] == ["test_recent_listed"]
        assert data["total"] == 1

    def test_recents_respect_the_limit(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """``limit`` caps the list, keeping the most recent entries."""
        for minutes, pid in enumerate(("test_limit_a", "test_limit_b", "test_limit_c"), start=1):
            _listing(db_session, test_organization, pid=pid)
            _recent(db_session, test_user, pid=pid, minutes_ago=minutes)

        data = authenticated_client.get("/api/v2/models/recents?limit=2").json()
        assert [i["id"] for i in data["items"]] == ["test_limit_a", "test_limit_b"]
        assert data["total"] == 2

    def test_recents_reject_an_out_of_range_limit(self, authenticated_client):
        """The limit is bounded — 0 and 51 are refused, not clamped silently."""
        assert authenticated_client.get("/api/v2/models/recents?limit=0").status_code == 422
        assert authenticated_client.get("/api/v2/models/recents?limit=51").status_code == 422

    def test_recents_require_authentication(self, client):
        """The list is per-user, so an anonymous caller gets nothing."""
        assert client.get("/api/v2/models/recents").status_code == 401

    def test_recents_are_scoped_to_the_caller(
        self, authenticated_client, db_session, test_user_2, test_organization
    ):
        """Another user's history never appears in mine."""
        _listing(db_session, test_organization, pid="test_recent_other_user")
        _recent(db_session, test_user_2, pid="test_recent_other_user")

        data = authenticated_client.get("/api/v2/models/recents").json()
        assert "test_recent_other_user" not in [i["id"] for i in data["items"]]


def _rows_for(db, user, pid) -> list[RecentModel]:
    return (
        db.query(RecentModel)
        .filter(RecentModel.user_id == user.id, RecentModel.model_project_id == pid)
        .all()
    )


class TestOpeningAModelRecordsIt:
    """Opening a marketplace listing is what puts it in "Recent".

    Nothing used to write this table at all — the list read a table only GDPR
    erasure and a backfill ever touched, so the tab showed an empty state for
    every account. The write goes where the visit is already recorded: the
    detail page the Recent cards themselves link to.
    """

    def test_opening_a_listing_puts_it_in_recents(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        _listing(db_session, test_organization, pid="test_open_records")

        assert (
            authenticated_client.get("/api/v2/models/catalog/test_open_records").status_code == 200
        )

        rows = _rows_for(db_session, test_user, "test_open_records")
        assert len(rows) == 1
        assert rows[0].access_count == "1"

        data = authenticated_client.get("/api/v2/models/recents").json()
        assert [i["id"] for i in data["items"]] == ["test_open_records"]
        assert data["items"][0]["access_count"] == 1

    def test_opening_twice_updates_the_same_row(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """A second visit moves the entry up the list instead of duplicating it.

        ``(user_id, model_project_id)`` is unique, so a read-then-write would
        raise here under any concurrency — two tabs, or an impatient double
        click. The upsert is what makes the second visit an update.
        """
        _listing(db_session, test_organization, pid="test_open_twice")

        authenticated_client.get("/api/v2/models/catalog/test_open_twice")
        first = _rows_for(db_session, test_user, "test_open_twice")[0].last_accessed

        authenticated_client.get("/api/v2/models/catalog/test_open_twice")
        db_session.expire_all()

        rows = _rows_for(db_session, test_user, "test_open_twice")
        assert len(rows) == 1
        assert rows[0].access_count == "2"
        assert rows[0].last_accessed >= first

    def test_an_anonymous_visit_records_nothing(self, client, db_session, test_organization):
        """The catalog is public, and a visitor with no account has no history."""
        _listing(db_session, test_organization, pid="test_open_anonymous")

        assert client.get("/api/v2/models/catalog/test_open_anonymous").status_code == 200

        assert (
            db_session.query(RecentModel)
            .filter(RecentModel.model_project_id == "test_open_anonymous")
            .count()
            == 0
        )

    # CONTRACT-TEST: a public path's opportunistic user survives its own auth session
    def test_it_works_when_the_auth_session_expires_its_instances(
        self, authenticated_client, db_session, test_user, test_organization, monkeypatch
    ):
        """The same visit, with the session settings production actually runs.

        On a public path the auth middleware authenticates in its own session
        and closes it *before* the handler runs. The suite hands that middleware
        a ``expire_on_commit=False`` sessionmaker, so instances stay readable
        afterwards and every other test here passes whether or not the handler
        can use them. Production uses the default, where the rollback expires
        them and reading ``user.id`` raises ``DetachedInstanceError`` — which the
        telemetry's broad except swallowed, dropping the write with a 200 on the
        wire. Recreating that here is the only way this file can tell.
        """
        production_like = sessionmaker(bind=db_session.get_bind(), expire_on_commit=True)
        monkeypatch.setattr(auth_middleware, "_session_factory", production_like)
        _listing(db_session, test_organization, pid="test_open_expiring_session")

        response = authenticated_client.get("/api/v2/models/catalog/test_open_expiring_session")

        assert response.status_code == 200
        assert len(_rows_for(db_session, test_user, "test_open_expiring_session")) == 1

    def test_a_failed_recent_write_still_serves_the_page(
        self, authenticated_client, db_session, test_organization, monkeypatch
    ):
        """The entry is a convenience; the listing is what the reader asked for."""
        _listing(db_session, test_organization, pid="test_open_failure")

        def _explode(*args, **kwargs):
            raise RuntimeError("cannot write recents")

        monkeypatch.setattr(favorites_service, "touch_recent", _explode)

        response = authenticated_client.get("/api/v2/models/catalog/test_open_failure")
        assert response.status_code == 200
        assert response.json()["id"] == "test_open_failure"
