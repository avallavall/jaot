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


# ---------------------------------------------------------------------------
# §8/S1 — dataset provenance on /solve/async executions
# ---------------------------------------------------------------------------

_TINY_PROBLEM = {
    "name": "tiny_lp",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
    "objective": {"sense": "maximize", "expression": "x"},
    "constraints": [{"name": "c1", "expression": "x <= 5"}],
    "options": {"time_limit_seconds": 10.0, "verbose": False},
}


def _stub_enqueue(monkeypatch, task_id: str = "fake-task-s1") -> None:
    """Stub solve_async.apply_async so POST /solve/async succeeds without a broker.

    Same broker-independent pattern as tests/api/test_auto_routing.py::test_async_hoist —
    the handler imports the task object locally, so patching its attribute is enough.
    P1.5 F0: the enqueue pre-generates the task id and submits it via ``task_id=``
    (insert-before-enqueue); the stub echoes that id back like real celery, so the
    pending row's celery_task_id == the id in the response. Assert against the
    response's ``execution_id`` (the row PK), not a hardcoded task id.
    """
    import app.domains.solver.tasks.solve_tasks as _solve_tasks_mod

    class _FakeAsyncResult:
        def __init__(self, tid: str) -> None:
            self.id = tid

    monkeypatch.setattr(
        _solve_tasks_mod.solve_async,
        "apply_async",
        lambda **kwargs: _FakeAsyncResult(kwargs.get("task_id") or task_id),
    )


def _solve_async_url(pid: str, dsid: str | None = None) -> str:
    url = f"/api/v2/solve/async?origin=visual_builder&source_kind=model_project&source_id={pid}"
    if dsid is not None:
        url += f"&dataset_id={dsid}"
    return url


class TestSolveDatasetProvenance:
    # CONTRACT-TEST: an async solve tagged with a dataset persists BOTH the dataset id
    # and a name SNAPSHOT on the ModelExecution row (history must survive dataset deletion).
    def test_async_solve_stores_dataset_id_and_name_snapshot(
        self, authenticated_client: TestClient, db_session: Session, monkeypatch
    ):
        from app.models.optimization_model import ModelExecution

        _stub_enqueue(monkeypatch)
        pid = _create_project(authenticated_client)["id"]
        ds = _create_dataset(authenticated_client, pid)
        resp = authenticated_client.post(_solve_async_url(pid, ds["id"]), json=_TINY_PROBLEM)
        assert resp.status_code == 200, resp.text
        row = (
            db_session.query(ModelExecution)
            .filter(ModelExecution.id == resp.json()["execution_id"])
            .first()
        )
        assert row is not None
        assert row.dataset_id == ds["id"]
        assert row.dataset_name == "Q3 forecast"
        assert row.model_project_id == pid

    def test_solve_without_dataset_leaves_columns_null(
        self, authenticated_client: TestClient, db_session: Session, monkeypatch
    ):
        from app.models.optimization_model import ModelExecution

        _stub_enqueue(monkeypatch, task_id="fake-task-s1-nods")
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(_solve_async_url(pid), json=_TINY_PROBLEM)
        assert resp.status_code == 200, resp.text
        row = (
            db_session.query(ModelExecution)
            .filter(ModelExecution.id == resp.json()["execution_id"])
            .first()
        )
        assert row is not None
        assert row.dataset_id is None
        assert row.dataset_name is None

    def test_history_keeps_the_name_after_dataset_deletion(
        self, authenticated_client: TestClient, monkeypatch
    ):
        # The owner's ask: "el historial debe decir qué dataset se usó" — even after
        # the dataset (working data, hard-deletable) is gone.
        _stub_enqueue(monkeypatch, task_id="fake-task-s1-del")
        pid = _create_project(authenticated_client)["id"]
        ds = _create_dataset(authenticated_client, pid)
        resp = authenticated_client.post(_solve_async_url(pid, ds["id"]), json=_TINY_PROBLEM)
        assert resp.status_code == 200, resp.text
        assert (
            authenticated_client.delete(f"/api/v2/projects/{pid}/datasets/{ds['id']}").status_code
            == 204
        )
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions").json()
        assert len(rows) == 1
        assert rows[0]["dataset_id"] == ds["id"]
        assert rows[0]["dataset_name"] == "Q3 forecast"

    def test_unknown_dataset_404s_before_charging_or_enqueueing(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        monkeypatch,
    ):
        from app.models.optimization_model import ModelExecution

        enqueued: list[str] = []

        import app.domains.solver.tasks.solve_tasks as _solve_tasks_mod

        def _record_enqueue(**kwargs):
            enqueued.append("called")
            raise AssertionError("apply_async must not be reached on a dataset 404")

        monkeypatch.setattr(_solve_tasks_mod.solve_async, "apply_async", _record_enqueue)
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _solve_async_url(pid, "mpd_does_not_exist_anywhere"), json=_TINY_PROBLEM
        )
        assert resp.status_code == 404, resp.text
        assert enqueued == []
        assert db_session.query(ModelExecution).filter_by(model_project_id=pid).first() is None

    # CONTRACT-TEST: a cross-org dataset_id on the solve request 404s with no oracle —
    # client-supplied ids must never resolve across orgs (the audit's cross-org lesson).
    def test_cross_org_dataset_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
        monkeypatch,
    ):
        _stub_enqueue(monkeypatch)
        foreign = _insert_foreign_dataset(db_session, test_organization_2, test_user_2)
        pid = _create_project(authenticated_client)["id"]
        cross = authenticated_client.post(_solve_async_url(pid, foreign.id), json=_TINY_PROBLEM)
        nonex = authenticated_client.post(
            _solve_async_url(pid, "mpd_does_not_exist_anywhere"), json=_TINY_PROBLEM
        )
        assert cross.status_code == 404, cross.text
        assert nonex.status_code == 404, nonex.text
        assert cross.json()["detail"] == nonex.json()["detail"]

    def test_own_dataset_from_another_project_is_404(
        self, authenticated_client: TestClient, monkeypatch
    ):
        # When the solve names a project, the dataset must belong to THAT project.
        _stub_enqueue(monkeypatch)
        pid_a = _create_project(authenticated_client, name="A")["id"]
        pid_b = _create_project(authenticated_client, name="B")["id"]
        ds_b = _create_dataset(authenticated_client, pid_b)
        resp = authenticated_client.post(_solve_async_url(pid_a, ds_b["id"]), json=_TINY_PROBLEM)
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# S2c — POST /projects/{id}/datasets/import (file -> data_json preview)
# ---------------------------------------------------------------------------

_DAT_FILE = b"set I := a b c;\nparam cap := 10;\nparam w := a 2, b 3, c 4;\n"


def _import_url(pid: str) -> str:
    return f"/api/v2/projects/{pid}/datasets/import"


class TestDatasetImport:
    def test_dat_file_parses_to_preview(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid), files={"file": ("q3_forecast.dat", _DAT_FILE, "text/plain")}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["suggested_name"] == "q3_forecast"
        assert body["data_json"] == {
            "sets": {"I": ["a", "b", "c"]},
            "params": {"cap": 10.0, "w": {"a": 2.0, "b": 3.0, "c": 4.0}},
        }
        # The preview is exactly what the normal create accepts.
        created = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets",
            json={"name": body["suggested_name"], "data_json": body["data_json"]},
        )
        assert created.status_code == 201, created.text

    def test_dat_parse_error_is_422_with_position(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid),
            files={"file": ("bad.dat", b"param w := a x;", "text/plain")},
        )
        assert resp.status_code == 422, resp.text
        assert "must end in a number" in resp.json()["detail"]
        assert "(pos" in resp.json()["detail"]

    def test_csv_one_param_with_header_and_filename_default(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        csv_bytes = b"origin,destination,cost\nA,1,4\nA,2,6.5\nB,1,3\n"
        resp = authenticated_client.post(
            _import_url(pid), files={"file": ("shipping cost.csv", csv_bytes, "text/csv")}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Param name defaults from the sanitized filename stem.
        assert body["data_json"] == {
            "params": {"shipping_cost": {"A,1": 4.0, "A,2": 6.5, "B,1": 3.0}}
        }

    def test_csv_param_name_override(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid),
            files={"file": ("whatever.csv", b"a,2\nb,3\n", "text/csv")},
            data={"param_name": "w"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_json"] == {"params": {"w": {"a": 2.0, "b": 3.0}}}

    def test_csv_ragged_rows_are_422(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid),
            files={"file": ("bad.csv", b"a,1,2\nb,3\n", "text/csv")},
        )
        assert resp.status_code == 422, resp.text
        assert "columns" in resp.json()["detail"]

    def test_json_file_round_trips(self, authenticated_client: TestClient):
        import json as _json

        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid),
            files={"file": ("data.json", _json.dumps(_DATA).encode(), "application/json")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_json"] == _DATA

    def test_json_bad_shape_is_422_with_compiler_message(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid),
            files={"file": ("data.json", b'{"sets": {"I": "abc"}}', "application/json")},
        )
        assert resp.status_code == 422, resp.text
        assert "must be a list" in resp.json()["detail"]

    def test_unsupported_extension_is_422(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid), files={"file": ("model.mps", b"NAME test", "text/plain")}
        )
        assert resp.status_code == 422, resp.text
        assert "unsupported file type" in resp.json()["detail"]

    def test_oversized_file_is_422(self, authenticated_client: TestClient, monkeypatch):
        from app.services import model_project_service as svc_mod

        monkeypatch.setattr(svc_mod, "MAX_DATASET_JSON_BYTES", 8)
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid), files={"file": ("big.dat", _DAT_FILE, "text/plain")}
        )
        assert resp.status_code == 422, resp.text
        assert "too large" in resp.json()["detail"]

    def test_non_utf8_file_is_422(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.post(
            _import_url(pid), files={"file": ("bad.dat", b"\xff\xfe\x00 binary", "text/plain")}
        )
        assert resp.status_code == 422, resp.text
        assert "not valid UTF-8" in resp.json()["detail"]

    # CONTRACT-TEST: import is org-scoped like every dataset surface (anti-oracle 404).
    def test_cross_tenant_project_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        foreign = _insert_foreign_dataset(db_session, test_organization_2, test_user_2)
        files = {"file": ("d.dat", _DAT_FILE, "text/plain")}
        cross = authenticated_client.post(_import_url(foreign.model_project_id), files=files)
        nonex = authenticated_client.post(_import_url("mp_does_not_exist_anywhere"), files=files)
        assert cross.status_code == 404, cross.text
        assert nonex.status_code == 404, nonex.text
        assert cross.json()["detail"] == nonex.json()["detail"]

    def test_import_requires_auth(self, client: TestClient):
        resp = client.post(_import_url("mp_x"), files={"file": ("d.dat", _DAT_FILE, "text/plain")})
        assert resp.status_code in (401, 403), resp.text

    def test_flat_model_json_gets_a_targeted_message(self, authenticated_client: TestClient):
        # The owner's TFM scenario files are complete MODELS (grounded variables,
        # baked data) — the dataset import must say so and point at the model
        # import path, not list the model's keys as "unknown".
        import json as _json

        pid = _create_project(authenticated_client)["id"]
        flat_model = {
            "name": "tfm_scenario",
            "variables": [{"name": "a_1_1", "type": "binary"}],
            "objective": {"sense": "minimize", "expression": "a_1_1"},
            "constraints": [{"name": "c1", "expression": "a_1_1 <= 1"}],
        }
        resp = authenticated_client.post(
            _import_url(pid),
            files={
                "file": ("scenario_01.json", _json.dumps(flat_model).encode(), "application/json")
            },
        )
        assert resp.status_code == 422, resp.text
        assert "complete MODEL" in resp.json()["detail"]
        assert "Import a file" in resp.json()["detail"]
