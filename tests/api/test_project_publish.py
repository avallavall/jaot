"""Tests for project-native marketplace publishing (P1.5 G2).

``POST /api/v2/projects/{id}/publish`` attaches a ``ModelProjectListing`` facet to the
project (+ pins the committed HEAD version) instead of copying the model into a catalog
row. The published listing then serves the marketplace browse/detail endpoints.
"""

from app.models import ModelProject, ModelProjectListing, ModelProjectVersion

_BODY = {
    "display_name": "My Published Model",
    "description": "A thorough description of the published optimization model.",
    "short_description": "Short one",
    "category": "logistics",
    "tags": ["routing", "vrp"],
    "is_public": True,
    "section_overview": "## Overview\nStuff.",
}


def _committed_project(db, org, user, *, pid) -> ModelProject:
    """A project with one committed version (publishable)."""
    project = ModelProject(
        id=pid,
        organization_id=org.id,
        created_by=user.id,
        name="Publishable Project",
        status="active",
        draft_model_json={"variables": []},
        committed_count=1,
    )
    db.add(project)
    db.flush()
    version = ModelProjectVersion(
        id=pid + "_v1",
        model_project_id=pid,
        organization_id=org.id,
        sequence=1,
        model_json={"variables": []},
        content_hash="hash_" + pid,
        commit_summary="Initial commit",
    )
    db.add(version)
    db.flush()
    project.current_version_id = version.id
    db.commit()
    return project


class TestProjectPublish:
    def test_publish_creates_listing(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _committed_project(db_session, test_organization, test_user, pid="proj_pub_ok")

        res = authenticated_client.post("/api/v2/projects/proj_pub_ok/publish", json=_BODY)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == "proj_pub_ok"
        assert body["display_name"] == "My Published Model"
        assert body["is_official"] is False

        listing = db_session.get(ModelProjectListing, "proj_pub_ok")
        assert listing is not None
        assert listing.status == "published"
        assert listing.author_organization_id == test_organization.id
        assert listing.pinned_version_id == "proj_pub_ok_v1"
        # No catalog copy is created — the fused publish is listing-only.
        from app.models import ModelCatalog

        assert db_session.get(ModelCatalog, "proj_pub_ok") is None

    def test_published_project_appears_in_browse(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _committed_project(db_session, test_organization, test_user, pid="proj_pub_browse")
        body = {**_BODY, "display_name": "uniquepublishedbrowse"}
        assert (
            authenticated_client.post(
                "/api/v2/projects/proj_pub_browse/publish", json=body
            ).status_code
            == 200
        )

        res = authenticated_client.get("/api/v2/models/catalog?search=uniquepublishedbrowse")
        assert res.status_code == 200, res.text
        ids = [i["id"] for i in res.json()["items"]]
        assert "proj_pub_browse" in ids

    def test_publish_requires_committed_version(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # A blank project with no committed version cannot be published.
        db_session.add(
            ModelProject(
                id="proj_pub_nover",
                organization_id=test_organization.id,
                created_by=test_user.id,
                name="No Version",
                status="active",
            )
        )
        db_session.commit()

        res = authenticated_client.post("/api/v2/projects/proj_pub_nover/publish", json=_BODY)
        assert res.status_code == 400, res.text
        assert "commit" in res.json()["detail"].lower()

    def test_republish_updates_listing(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _committed_project(db_session, test_organization, test_user, pid="proj_pub_re")
        authenticated_client.post("/api/v2/projects/proj_pub_re/publish", json=_BODY)

        updated = {**_BODY, "display_name": "Renamed Model", "is_public": False}
        res = authenticated_client.post("/api/v2/projects/proj_pub_re/publish", json=updated)
        assert res.status_code == 200, res.text
        assert res.json()["display_name"] == "Renamed Model"

        listings = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == "proj_pub_re")
            .all()
        )
        assert len(listings) == 1  # upsert, not a second row
        assert listings[0].is_public is False

    def test_publish_other_org_404(
        self, authenticated_client, db_session, test_organization_2, test_user
    ):
        # A project owned by another org must not be publishable by this user.
        _committed_project(db_session, test_organization_2, test_user, pid="proj_pub_foreign")
        res = authenticated_client.post("/api/v2/projects/proj_pub_foreign/publish", json=_BODY)
        assert res.status_code == 404, res.text

    # CONTRACT-TEST: an adopted marketplace fork needs an OWN commit before republish
    # (owner decision 2026-07-17: derivative works welcome, 1:1 authorship clones not).
    def test_publish_adopted_unmodified_400(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        project = _committed_project(db_session, test_organization, test_user, pid="proj_pub_adopt")
        # As seeded by POST /projects/from-marketplace: provenance + the auto v1 commit.
        project.source_type = "marketplace"
        project.committed_count = 1
        db_session.commit()

        res = authenticated_client.post("/api/v2/projects/proj_pub_adopt/publish", json=_BODY)
        assert res.status_code == 400, res.text
        assert "adopted" in res.json()["detail"].lower()

    def test_publish_adopted_after_own_commit_succeeds(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        project = _committed_project(
            db_session, test_organization, test_user, pid="proj_pub_adopt_mod"
        )
        project.source_type = "marketplace"
        # The adopter committed a change of their own on top of the adoption commit
        # (commit_version dedups no-change commits, so count>1 really means modified).
        project.committed_count = 2
        db_session.commit()

        res = authenticated_client.post("/api/v2/projects/proj_pub_adopt_mod/publish", json=_BODY)
        assert res.status_code == 200, res.text
