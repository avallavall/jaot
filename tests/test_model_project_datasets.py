"""Tests for the ModelProject dataset API (/api/v2/projects/{id}/datasets) — §8.

A dataset is a named data bundle ("scenario"): set members + param values that
fill a declaration-only JModel source at compile time. Covers CRUD, the strict
data_json validation (shape / size), duplicate-name conflicts, org scoping with
anti-oracle 404s, and auth.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.model_project import ModelProject, ModelProjectDataset
from tests._helpers.anti_oracle import (
    assert_cross_tenant_404_anti_oracle,
    assert_cross_tenant_404_anti_oracle_write,
)

_DATA = {
    "sets": {"ITEMS": ["a", "b"]},
    "params": {"w": {"a": 2, "b": 3}, "cap": 1},
}


def _create_project(client: TestClient, name: str = "Dataset Host") -> dict:
    resp = client.post("/api/v2/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_dataset(
    client: TestClient, project_id: str, name: str = "Q3 forecast", data: dict | None = None
) -> dict:
    resp = client.post(
        f"/api/v2/projects/{project_id}/datasets",
        json={"name": name, "description": "seed", "data_json": data or _DATA},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _insert_foreign_dataset(db: Session, org: Organization, user: User) -> ModelProjectDataset:
    project = ModelProject(
        organization_id=org.id, created_by=user.id, name="Foreign", status="active"
    )
    db.add(project)
    db.flush()
    dataset = ModelProjectDataset(
        model_project_id=project.id,
        organization_id=org.id,
        created_by=user.id,
        name="Foreign DS",
        data_json=_DATA,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


class TestDatasetCrud:
    def test_create_returns_201_with_mpd_prefix_and_values(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        data = _create_dataset(authenticated_client, pid)
        assert data["id"].startswith("mpd_")
        assert data["model_project_id"] == pid
        assert data["name"] == "Q3 forecast"
        assert data["data_json"] == _DATA

    def test_list_is_compact_and_ordered(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        _create_dataset(authenticated_client, pid, name="first")
        _create_dataset(authenticated_client, pid, name="second")
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/datasets").json()
        assert [r["name"] for r in rows] == ["first", "second"]
        # Values can be MBs — the list view must not carry them.
        assert all("data_json" not in r for r in rows)

    def test_get_returns_full_values(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        row = authenticated_client.get(f"/api/v2/projects/{pid}/datasets/{dsid}").json()
        assert row["data_json"] == _DATA

    def test_update_renames_and_replaces_values(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        new_data = {"sets": {"ITEMS": ["z"]}, "params": {"w": {"z": 9}, "cap": 2}}
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/datasets/{dsid}",
            json={"name": "Q4 forecast", "data_json": new_data},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Q4 forecast"
        assert resp.json()["data_json"] == new_data

    def test_partial_update_keeps_other_fields(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/datasets/{dsid}", json={"description": "updated"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["description"] == "updated"
        assert resp.json()["name"] == "Q3 forecast"
        assert resp.json()["data_json"] == _DATA

    def test_delete_removes_the_dataset(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        resp = authenticated_client.delete(f"/api/v2/projects/{pid}/datasets/{dsid}")
        assert resp.status_code == 204, resp.text
        assert (
            authenticated_client.get(f"/api/v2/projects/{pid}/datasets/{dsid}").status_code == 404
        )

    def test_deleting_the_project_cascades_its_datasets(
        self, authenticated_client: TestClient, db_session: Session
    ):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        assert (
            authenticated_client.patch(
                f"/api/v2/projects/{pid}", json={"status": "archived"}
            ).status_code
            == 200
        )
        resp = authenticated_client.delete(f"/api/v2/projects/{pid}?permanent=true")
        assert resp.status_code == 204, resp.text
        assert db_session.query(ModelProjectDataset).filter_by(id=dsid).first() is None


class TestDatasetValidation:
    def test_invalid_shape_is_422_with_the_compiler_message(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets",
            json={"name": "bad", "data_json": {"sets": {"I": "abc"}}},
        )
        assert resp.status_code == 422, resp.text
        assert "must be a list" in resp.json()["detail"]

    def test_unknown_top_level_key_is_422(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets",
            json={"name": "bad", "data_json": {"bogus": {}}},
        )
        assert resp.status_code == 422, resp.text
        assert "unknown top-level" in resp.json()["detail"]

    def test_update_with_invalid_values_is_422_and_keeps_the_old_ones(
        self, authenticated_client: TestClient
    ):
        pid = _create_project(authenticated_client)["id"]
        dsid = _create_dataset(authenticated_client, pid)["id"]
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/datasets/{dsid}",
            json={"data_json": {"params": {"w": {"a": "not-a-number"}}}},
        )
        assert resp.status_code == 422, resp.text
        row = authenticated_client.get(f"/api/v2/projects/{pid}/datasets/{dsid}").json()
        assert row["data_json"] == _DATA

    def test_oversized_dataset_is_422(self, authenticated_client: TestClient, monkeypatch):
        from app.services import model_project_service as svc

        monkeypatch.setattr(svc, "MAX_DATASET_JSON_BYTES", 64)
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets",
            json={"name": "big", "data_json": _DATA},
        )
        assert resp.status_code == 422, resp.text
        assert "too large" in resp.json()["detail"]

    def test_blank_name_is_422(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets", json={"name": "   ", "data_json": _DATA}
        )
        assert resp.status_code == 422, resp.text

    def test_duplicate_name_is_409(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        _create_dataset(authenticated_client, pid, name="same")
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets", json={"name": "same", "data_json": _DATA}
        )
        assert resp.status_code == 409, resp.text

    def test_rename_onto_an_existing_name_is_409(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        _create_dataset(authenticated_client, pid, name="taken")
        dsid = _create_dataset(authenticated_client, pid, name="renameme")["id"]
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/datasets/{dsid}", json={"name": "taken"}
        )
        assert resp.status_code == 409, resp.text

    def test_same_name_in_another_project_is_fine(self, authenticated_client: TestClient):
        pid_a = _create_project(authenticated_client, name="A")["id"]
        pid_b = _create_project(authenticated_client, name="B")["id"]
        _create_dataset(authenticated_client, pid_a, name="shared")
        _create_dataset(authenticated_client, pid_b, name="shared")


class TestDatasetTenancy:
    # CONTRACT-TEST: datasets are org-scoped — cross-org access 404s with no oracle
    def test_get_cross_tenant_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        foreign = _insert_foreign_dataset(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle(
            authenticated_client,
            endpoint_template=(f"/api/v2/projects/{foreign.model_project_id}/datasets/{{id}}"),
            cross_tenant_resource_id=foreign.id,
        )

    def test_write_cross_tenant_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        foreign = _insert_foreign_dataset(db_session, test_organization_2, test_user_2)
        template = f"/api/v2/projects/{foreign.model_project_id}/datasets/{{id}}"
        assert_cross_tenant_404_anti_oracle_write(
            authenticated_client,
            "put",
            template,
            foreign.id,
            body={"name": "hijack"},
        )
        assert_cross_tenant_404_anti_oracle_write(
            authenticated_client, "delete", template, foreign.id
        )

    def test_foreign_dataset_behind_own_project_id_is_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        # A foreign dataset id can never be reached through one of MY project ids —
        # the dataset filter pins BOTH the org and the project.
        foreign = _insert_foreign_dataset(db_session, test_organization_2, test_user_2)
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.get(f"/api/v2/projects/{pid}/datasets/{foreign.id}")
        assert resp.status_code == 404, resp.text

    def test_own_dataset_behind_the_wrong_project_is_404(self, authenticated_client: TestClient):
        pid_a = _create_project(authenticated_client, name="A")["id"]
        pid_b = _create_project(authenticated_client, name="B")["id"]
        dsid = _create_dataset(authenticated_client, pid_a)["id"]
        resp = authenticated_client.get(f"/api/v2/projects/{pid_b}/datasets/{dsid}")
        assert resp.status_code == 404, resp.text


class TestDatasetAuth:
    def test_list_requires_auth(self, client: TestClient):
        resp = client.get("/api/v2/projects/mp_x/datasets")
        assert resp.status_code in (401, 403), resp.text

    def test_create_requires_auth(self, client: TestClient):
        resp = client.post("/api/v2/projects/mp_x/datasets", json={"name": "n", "data_json": _DATA})
        assert resp.status_code in (401, 403), resp.text
