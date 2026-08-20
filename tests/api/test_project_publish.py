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
        # Publishing writes a listing facet and nothing else: the pre-fusion
        # ``model_catalog`` table this used to assert against no longer exists
        # (D-26), which makes the point permanently rather than per-run.
        from sqlalchemy import inspect as sa_inspect

        assert "model_catalog" not in sa_inspect(db_session.get_bind()).get_table_names()

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
        # CONTRACT-TEST: the two publish refusals ask the author for different work,
        # so they must be distinguishable without parsing English. A browser that
        # cannot tell them apart answers "commit first" to someone who did commit.
        assert res.json()["code"] == "projects.publish_needs_commit"

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
        # ...and it must NOT read as the no-commit refusal: this project has one.
        assert res.json()["code"] == "projects.publish_needs_own_change"

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


class TestArchiveWithdrawsListing:
    """Archiving a published project takes its listing off the marketplace.

    Found by driving the app with two browsers (QA sweep, 2026-08-20): a model
    archived from My models stayed searchable, openable and copyable by anyone.
    An archived project refuses every write, so its listing could never be
    updated again, and archiving is the only road to a permanent delete.
    """

    def test_archive_withdraws_a_published_listing(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _committed_project(db_session, test_organization, test_user, pid="proj_arch_pub")
        body = {**_BODY, "display_name": "uniquearchivewithdraw"}
        assert (
            authenticated_client.post(
                "/api/v2/projects/proj_arch_pub/publish", json=body
            ).status_code
            == 200
        )

        assert authenticated_client.delete("/api/v2/projects/proj_arch_pub").status_code == 204

        db_session.expire_all()
        assert db_session.get(ModelProjectListing, "proj_arch_pub").status == "unpublished"
        res = authenticated_client.get("/api/v2/models/catalog?search=uniquearchivewithdraw")
        assert "proj_arch_pub" not in [i["id"] for i in res.json()["items"]]
        assert authenticated_client.get("/api/v2/models/catalog/proj_arch_pub").status_code == 404

    def test_archive_by_patch_withdraws_it_too(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # The list view archives with PATCH status, the workbench with DELETE.
        # Both are the same action to the person doing it.
        _committed_project(db_session, test_organization, test_user, pid="proj_arch_patch")
        authenticated_client.post("/api/v2/projects/proj_arch_patch/publish", json=_BODY)

        res = authenticated_client.patch(
            "/api/v2/projects/proj_arch_patch", json={"status": "archived"}
        )
        assert res.status_code == 200, res.text

        db_session.expire_all()
        assert db_session.get(ModelProjectListing, "proj_arch_patch").status == "unpublished"

    def test_restoring_does_not_publish_it_again(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # Putting a model back on the marketplace is the author's call, never a
        # side effect of restoring it.
        _committed_project(db_session, test_organization, test_user, pid="proj_arch_restore")
        authenticated_client.post("/api/v2/projects/proj_arch_restore/publish", json=_BODY)
        authenticated_client.delete("/api/v2/projects/proj_arch_restore")

        res = authenticated_client.patch(
            "/api/v2/projects/proj_arch_restore", json={"status": "active"}
        )
        assert res.status_code == 200, res.text

        db_session.expire_all()
        assert db_session.get(ModelProjectListing, "proj_arch_restore").status == "unpublished"

    def test_archiving_a_never_published_project_is_unaffected(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _committed_project(db_session, test_organization, test_user, pid="proj_arch_nolisting")

        assert (
            authenticated_client.delete("/api/v2/projects/proj_arch_nolisting").status_code == 204
        )

        db_session.expire_all()
        assert db_session.get(ModelProjectListing, "proj_arch_nolisting") is None
        assert db_session.get(ModelProject, "proj_arch_nolisting").status == "archived"
