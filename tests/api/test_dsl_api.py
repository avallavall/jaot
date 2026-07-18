"""Tests for the JModel DSL endpoints (P5.2).

Covers the JAOT_DSL feature gate (404 when off), the status probe, successful
compilation, structured compile errors, and auth. Mirrors the toggling pattern in
``test_solve_maintenance_gate.py`` (PSS.set on the shared db_session).
"""

import pytest

from app.services.platform_settings_service import PlatformSettingsService as PSS

SMALL_SOURCE = """
var x >= 0;
minimize obj: x;
subject to c: x >= 5;
"""


@pytest.fixture
def enable_dsl(db_session):
    """Turn JAOT_DSL ON for a single test, then restore OFF."""
    PSS.set(db_session, "JAOT_DSL", "true")
    db_session.commit()
    yield
    PSS.set(db_session, "JAOT_DSL", "false")
    db_session.commit()


@pytest.mark.integration
def test_status_disabled_by_default(authenticated_client, test_organization, db_session):
    resp = authenticated_client.get("/api/v2/dsl/status")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False}


@pytest.mark.integration
def test_status_enabled_when_flag_on(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.get("/api/v2/dsl/status")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": True}


# CONTRACT-TEST: the JModel DSL ships dark — /dsl/compile is invisible (404, not 403)
# whenever the JAOT_DSL flag is off, so the feature cannot be probed on prod instances.
@pytest.mark.integration
def test_compile_404_when_flag_off(authenticated_client, test_organization, db_session):
    """The compile endpoint is invisible (404) while the feature ships dark."""
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "dsl_disabled"


@pytest.mark.integration
def test_compile_ok_when_flag_on(authenticated_client, test_organization, db_session, enable_dsl):
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    problem = body["problem"]
    assert [v["name"] for v in problem["variables"]] == ["x"]
    assert problem["objective"]["expression"] == "x"
    assert problem["constraints"][0]["expression"] == "x >= 5"


@pytest.mark.integration
def test_compile_reports_structured_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """A syntax error is a 200 with ok=false + message + position (no 4xx)."""
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "set S := {a, b}\nvar x >= 0;"},  # missing ';' after the set
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["problem"] is None
    assert body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_compile_unknown_symbol_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "var x >= 0; minimize obj: x + y; subject to c: x >= 1;"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "unknown symbol" in body["error"]["message"]


# CONTRACT-TEST: /dsl/compile requires authentication — the compiler is CPU-bound and
# must never be reachable anonymously.
@pytest.mark.integration
def test_compile_requires_auth(client):
    resp = client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_status_requires_auth(client):
    resp = client.get("/api/v2/dsl/status")
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_compile_undefined_set_is_structured_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """Regression: `var x{J}` with J undeclared used to escape as a KeyError -> 500."""
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": "set I := {a};\nvar x{J};\nminimize obj: x[a];"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "unknown set 'J'" in body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_compile_error_position_is_exact(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """The editor points at the offending character — the offset must be exact."""
    source = "var x >= 0;\nminimize obj: x + qq;\nsubject to c: x >= 1;"
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": source})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["position"] == source.index("qq")


@pytest.mark.integration
def test_compile_internal_error_is_structured_not_500(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    """A compiler bug must surface as ok=false (the editor calls this per keystroke)."""

    def _boom(source):
        raise RuntimeError("compiler bug")

    monkeypatch.setattr("app.api.v2.dsl.compile_jmodel", _boom)
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": SMALL_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["message"] == "internal compiler error"


@pytest.mark.integration
def test_compile_source_size_cap(authenticated_client, test_organization, db_session, enable_dsl):
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": "x" * 1_000_001})
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# Datasets (§8) — compile a declaration-only source against a named dataset
# --------------------------------------------------------------------------- #

PARAMETRIC_SOURCE = """
set I;
param w{I};
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to c: sum{i in I} x[i] <= 1;
"""

DATASET_JSON = {"sets": {"I": ["a", "b"]}, "params": {"w": {"a": 2, "b": 3}}}


def _create_dataset(client, data=None) -> str:
    pid = client.post("/api/v2/projects", json={"name": "DSL data host"}).json()["id"]
    resp = client.post(
        f"/api/v2/projects/{pid}/datasets",
        json={"name": "scenario 1", "data_json": data or DATASET_JSON},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.integration
def test_compile_with_dataset_fills_declarations(
    authenticated_client, test_organization, db_session, enable_dsl
):
    dsid = _create_dataset(authenticated_client)
    resp = authenticated_client.post(
        "/api/v2/dsl/compile", json={"source": PARAMETRIC_SOURCE, "dataset_id": dsid}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, body
    problem = body["problem"]
    assert [v["name"] for v in problem["variables"]] == ["x_a", "x_b"]
    assert problem["objective"]["expression"] == "2*x_a + 3*x_b"


@pytest.mark.integration
def test_compile_declaration_only_without_dataset_names_the_missing_symbol(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post("/api/v2/dsl/compile", json={"source": PARAMETRIC_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "set 'I' has no members" in body["error"]["message"]


@pytest.mark.integration
def test_compile_with_unknown_dataset_is_a_structured_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/compile",
        json={"source": PARAMETRIC_SOURCE, "dataset_id": "mpd_does_not_exist"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert "dataset not found" in body["error"]["message"]


# CONTRACT-TEST: /dsl/compile dataset resolution is org-scoped — another org's
# dataset id behaves exactly like a nonexistent one (no cross-org oracle).
@pytest.mark.integration
def test_compile_with_foreign_dataset_matches_nonexistent(
    authenticated_client,
    test_organization,
    db_session,
    enable_dsl,
    test_organization_2,
    test_user_2,
):
    from app.models.model_project import ModelProject, ModelProjectDataset

    project = ModelProject(
        organization_id=test_organization_2.id,
        created_by=test_user_2.id,
        name="Foreign",
        status="active",
    )
    db_session.add(project)
    db_session.flush()
    foreign = ModelProjectDataset(
        model_project_id=project.id,
        organization_id=test_organization_2.id,
        created_by=test_user_2.id,
        name="Foreign DS",
        data_json=DATASET_JSON,
    )
    db_session.add(foreign)
    db_session.commit()

    def _compile_error(dataset_id: str) -> str:
        resp = authenticated_client.post(
            "/api/v2/dsl/compile",
            json={"source": PARAMETRIC_SOURCE, "dataset_id": dataset_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is False
        return body["error"]["message"]

    assert _compile_error(foreign.id) == _compile_error("mpd_does_not_exist_anywhere")


@pytest.mark.integration
def test_compile_dataset_overrides_inline_defaults(
    authenticated_client, test_organization, db_session, enable_dsl
):
    inline = """
    set I := {a, b};
    param w{I} := a 1, b 1;
    var x{I} binary;
    maximize obj: sum{i in I} w[i] * x[i];
    subject to c: sum{i in I} x[i] <= 1;
    """
    dsid = _create_dataset(authenticated_client, data={"params": {"w": {"a": 7, "b": 9}}})
    resp = authenticated_client.post(
        "/api/v2/dsl/compile", json={"source": inline, "dataset_id": dsid}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, body
    assert body["problem"]["objective"]["expression"] == "7*x_a + 9*x_b"


# --------------------------------------------------------------------------- #
# B3 — POST /dsl/generate (AI-generate a JModel source, vision + compile loop)
# --------------------------------------------------------------------------- #

GEN_GOOD = (
    "```jmodel\n"
    "set I := {a, b};\n"
    "param w{I} := a 2, b 3;\n"
    "var x{I} binary;\n"
    "maximize obj: sum{i in I} w[i] * x[i];\n"
    "subject to pick: sum{i in I} x[i] <= 1;\n"
    "```"
)
GEN_BROKEN = "```jmodel\nvar x binary\nmaximize obj: x;\n```"  # missing ';'


class _GenBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _GenUsage:
    input_tokens = 120
    output_tokens = 60


class _GenResp:
    def __init__(self, text: str) -> None:
        self.content = [_GenBlock(text)]
        self.usage = _GenUsage()


class _GenMessages:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0
        self.received = []

    async def create(self, **kwargs):
        self.received.append(kwargs["messages"])
        reply = self._replies[self.calls]
        self.calls += 1
        return _GenResp(reply)


class FakeGenClient:
    def __init__(self, replies):
        self.messages = _GenMessages(replies)


def _patch_client(monkeypatch, replies):
    """Patch the dsl route's Anthropic factory to a fake returning canned replies."""
    fake = FakeGenClient(replies)
    monkeypatch.setattr("app.api.v2.dsl.get_anthropic_client", lambda db=None: fake)
    return fake


# CONTRACT-TEST: /dsl/generate ships dark with the rest of the DSL — 404 (not 403)
# whenever JAOT_DSL is off, so the feature cannot be probed on prod instances.
@pytest.mark.integration
def test_generate_404_when_flag_off(authenticated_client, test_organization, db_session):
    resp = authenticated_client.post("/api/v2/dsl/generate", json={"description": "a knapsack"})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dsl_disabled"


@pytest.mark.integration
def test_generate_requires_auth(client):
    resp = client.post("/api/v2/dsl/generate", json={"description": "a knapsack"})
    assert resp.status_code in (401, 403), resp.text


@pytest.mark.integration
def test_generate_happy_path_returns_compiling_source(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    _patch_client(monkeypatch, [GEN_GOOD])
    resp = authenticated_client.post(
        "/api/v2/dsl/generate", json={"description": "pick the best single item"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["attempts"] == 1
    assert "var x{I} binary;" in body["source"]


@pytest.mark.integration
def test_generate_retries_on_compile_error(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    """A broken first draft is fed the compile error and corrected on retry."""
    fake = _patch_client(monkeypatch, [GEN_BROKEN, GEN_GOOD])
    resp = authenticated_client.post(
        "/api/v2/dsl/generate", json={"description": "pick the best item"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["attempts"] == 2
    # Second call carried the failure back: user, assistant(raw), user(retry).
    assert len(fake.messages.received[1]) == 3


@pytest.mark.integration
def test_generate_returns_best_effort_when_never_compiles(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    _patch_client(monkeypatch, [GEN_BROKEN, GEN_BROKEN, GEN_BROKEN])
    resp = authenticated_client.post("/api/v2/dsl/generate", json={"description": "x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["source"]  # editable best-effort draft still returned
    assert body["error"]["message"]  # last compile error surfaced


@pytest.mark.integration
def test_generate_forwards_vision_attachment(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    """An image rides to the model as a native vision block (no OCR)."""
    fake = _patch_client(monkeypatch, [GEN_GOOD])
    resp = authenticated_client.post(
        "/api/v2/dsl/generate",
        json={
            "description": "",
            "attachments": [{"media_type": "image/png", "data": "QUJD"}],
        },
    )
    assert resp.status_code == 200, resp.text
    first_turn = fake.messages.received[0][0]["content"]
    kinds = [b["type"] for b in first_turn]
    assert "image" in kinds


@pytest.mark.integration
def test_generate_requires_description_or_attachment(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post("/api/v2/dsl/generate", json={"description": "   "})
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_generate_rejects_unknown_attachment_type(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/generate",
        json={
            "description": "a model",
            "attachments": [{"media_type": "image/tiff", "data": "QUJD"}],
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_generate_moderation_blocks_offensive(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/generate", json={"description": "write me a fucking poem"}
    )
    assert resp.status_code == 422, resp.text


# CONTRACT-TEST: /dsl/generate honors the monthly AI budget pause exactly like the chat
# assistant — a platform-key run is refused (403) once the budget is exhausted.
@pytest.mark.integration
def test_generate_paused_when_budget_exhausted(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    _patch_client(monkeypatch, [GEN_GOOD])
    monkeypatch.setattr("app.api.v2.dsl.is_llm_budget_exceeded", lambda db: True)
    resp = authenticated_client.post("/api/v2/dsl/generate", json={"description": "a knapsack"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["reason"] == "llm_monthly_budget_exhausted"


# CONTRACT-TEST: standalone LLM spend (B3) is booked into a hidden "sys:" bookkeeping
# conversation so it counts toward the monthly budget, and that conversation NEVER
# leaks into the user's conversation list.
@pytest.mark.integration
def test_standalone_spend_is_booked_and_hidden(
    authenticated_client, test_organization, test_user, db_session
):
    from app.models.llm_conversation import LLMConversation, LLMMessage
    from app.services.llm.cost_tracking import (
        get_month_cost_eur,
        record_standalone_llm_spend,
    )

    before = get_month_cost_eur(db_session)
    record_standalone_llm_spend(
        db_session,
        org_id=test_organization.id,
        user_id=test_user.id,
        model="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        summary="JModel AI generation (test)",
    )

    ledger = (
        db_session.query(LLMConversation)
        .filter(
            LLMConversation.organization_id == test_organization.id,
            LLMConversation.model_id == "sys:jmodel-ai",
        )
        .one()
    )
    msg = db_session.query(LLMMessage).filter(LLMMessage.conversation_id == ledger.id).one()
    assert msg.cost_eur is not None and float(msg.cost_eur) > 0
    assert get_month_cost_eur(db_session) > before  # counts toward the budget

    # The ledger conversation is invisible in the user's conversation list.
    listed = authenticated_client.get("/api/v2/llm/conversations").json()
    assert all(item["id"] != ledger.id for item in listed.get("items", []))


@pytest.mark.integration
def test_generate_source_size_cap_on_current_source(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/generate",
        json={"description": "refine", "current_source": "x" * 1_000_001},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_gate_cache_serves_stale_within_ttl(db_session, monkeypatch):
    """The production gate path caches the flag for 5s (the test bypass skips it, so
    this exercises the cached branch explicitly with controlled time)."""
    from app.api.v2.deps import dsl_feature_gate as gate

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    now = [1000.0]
    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    monkeypatch.setitem(gate._cache, "value", False)
    monkeypatch.setitem(gate._cache, "expires_at", 0.0)

    PSS.set(db_session, "JAOT_DSL", "true")
    db_session.commit()
    assert gate._is_on(db_session) is True  # fresh read, cached until t+5

    PSS.set(db_session, "JAOT_DSL", "false")
    db_session.commit()
    assert gate._is_on(db_session) is True  # stale-but-within-TTL: cache still serves ON

    now[0] = 1006.0
    assert gate._is_on(db_session) is False  # TTL expired: fresh read sees OFF


# ---------------------------------------------------------------------------
# S2a — POST /dsl/inspect (parse-only declarations for the dataset skeleton)
# ---------------------------------------------------------------------------

DECL_ONLY_SOURCE = """
set I;
param w{I};
param cap;
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to c: sum{i in I} x[i] <= cap;
"""


# CONTRACT-TEST: /dsl/inspect ships dark behind the same gate as compile (404 when off).
@pytest.mark.integration
def test_inspect_404_when_flag_off(authenticated_client, test_organization, db_session):
    resp = authenticated_client.post("/api/v2/dsl/inspect", json={"source": DECL_ONLY_SOURCE})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dsl_disabled"


@pytest.mark.integration
def test_inspect_lists_declaration_only_symbols(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """The whole point of inspect: it succeeds where compile errors (no data)."""
    resp = authenticated_client.post("/api/v2/dsl/inspect", json={"source": DECL_ONLY_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["sets"] == [{"name": "I", "has_inline_values": False}]
    by_name = {p["name"]: p for p in body["params"]}
    assert by_name["w"] == {
        "name": "w",
        "index_sets": ["I"],
        "arity": 1,
        "has_inline_values": False,
    }
    assert by_name["cap"] == {
        "name": "cap",
        "index_sets": [],
        "arity": 0,
        "has_inline_values": False,
    }


@pytest.mark.integration
def test_inspect_marks_inline_values(
    authenticated_client, test_organization, db_session, enable_dsl
):
    src = "set I := {a, b};\nparam w{I} := a 2, b 3;\nvar x{I} binary;\n"
    src += "maximize obj: sum{i in I} w[i] * x[i];\nsubject to c: sum{i in I} x[i] <= 1;"
    resp = authenticated_client.post("/api/v2/dsl/inspect", json={"source": src})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["sets"][0]["has_inline_values"] is True
    assert body["params"][0]["has_inline_values"] is True


@pytest.mark.integration
def test_inspect_reports_structured_parse_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/inspect", json={"source": "set S := {a, b}\nvar x >= 0;"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["sets"] is None
    assert body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_inspect_requires_auth(client):
    resp = client.post("/api/v2/dsl/inspect", json={"source": DECL_ONLY_SOURCE})
    assert resp.status_code in (401, 403), resp.text


# --------------------------------------------------------------------------- #
# LaTeX pretty-printer (B1) — the JModel split-pane math view
# --------------------------------------------------------------------------- #

LATEX_SOURCE = """
set I := {a, b};
param w{I} := a 2, b 3;
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to pick{i in I}: x[i] <= 1;
"""


# CONTRACT-TEST: /dsl/latex ships dark behind the same gate as compile (404 when off).
@pytest.mark.integration
def test_latex_404_when_flag_off(authenticated_client, test_organization, db_session):
    resp = authenticated_client.post("/api/v2/dsl/latex", json={"source": LATEX_SOURCE})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dsl_disabled"


@pytest.mark.integration
def test_latex_renders_symbolic_model(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post("/api/v2/dsl/latex", json={"source": LATEX_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["error"] is None
    model = body["model"]
    assert model["objective"]["label"] == "obj"
    assert model["objective"]["latex"].startswith("\\max \\quad \\sum_{i \\in I}")
    # The constraint family keeps its ∀ quantifier (not flattened to scalar rows).
    assert len(model["constraints"]) == 1
    assert "\\forall" in model["constraints"][0]["latex"]
    assert model["constraints"][0]["label"] == "pick"
    assert [v["label"] for v in model["variables"]] == ["x"]
    assert "\\{0, 1\\}" in model["variables"][0]["latex"]


@pytest.mark.integration
def test_latex_declaration_only_source_succeeds(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """Parse-only, so a declaration-only source renders (compile would error)."""
    resp = authenticated_client.post("/api/v2/dsl/latex", json={"source": DECL_ONLY_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, body
    assert body["model"]["objective"]["latex"].startswith("\\max \\quad")


@pytest.mark.integration
def test_latex_reports_structured_parse_error(
    authenticated_client, test_organization, db_session, enable_dsl
):
    resp = authenticated_client.post(
        "/api/v2/dsl/latex", json={"source": "set S := {a, b}\nvar x >= 0;"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["model"] is None
    assert body["error"]["message"]
    assert body["error"]["position"] is not None


@pytest.mark.integration
def test_latex_internal_error_is_structured_not_500(
    authenticated_client, test_organization, db_session, enable_dsl, monkeypatch
):
    """A renderer bug must surface as ok=false (the pane refreshes per keystroke)."""

    def _boom(source):
        raise RuntimeError("renderer bug")

    monkeypatch.setattr("app.api.v2.dsl.latexify", _boom)
    resp = authenticated_client.post("/api/v2/dsl/latex", json={"source": LATEX_SOURCE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["message"] == "internal compiler error"


@pytest.mark.integration
def test_latex_source_size_cap(authenticated_client, test_organization, db_session, enable_dsl):
    resp = authenticated_client.post("/api/v2/dsl/latex", json={"source": "x" * 1_000_001})
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
def test_latex_requires_auth(client):
    resp = client.post("/api/v2/dsl/latex", json={"source": LATEX_SOURCE})
    assert resp.status_code in (401, 403), resp.text


# --------------------------------------------------------------------------- #
# De-grounder (B2) — flat problem → compact JModel draft
# --------------------------------------------------------------------------- #


def _compile(client, source: str) -> dict:
    resp = client.post("/api/v2/dsl/compile", json={"source": source})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, body
    return body["problem"]


# CONTRACT-TEST: /dsl/deground ships dark behind the same gate as compile (404 when off).
@pytest.mark.integration
def test_deground_404_when_flag_off(authenticated_client, test_organization, db_session):
    resp = authenticated_client.post("/api/v2/dsl/deground", json={"problem": {"variables": []}})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "dsl_disabled"


@pytest.mark.integration
def test_deground_returns_compact_source_that_round_trips(
    authenticated_client, test_organization, db_session, enable_dsl
):
    problem = _compile(authenticated_client, LATEX_SOURCE)
    resp = authenticated_client.post("/api/v2/dsl/deground", json={"problem": problem})
    assert resp.status_code == 200, resp.text
    source = resp.json()["source"]
    assert source is not None
    assert "sum{" in source and "var x{" in source
    # Honest by construction: the draft recompiles to a valid problem.
    recompiled = _compile(authenticated_client, source)
    assert {v["name"] for v in recompiled["variables"]} == {v["name"] for v in problem["variables"]}


@pytest.mark.integration
def test_deground_small_scalar_model_gets_a_flat_jmodel(
    authenticated_client, test_organization, db_session, enable_dsl
):
    """A small model with no indexed families de-grounds as a plain scalar JModel."""
    problem = _compile(authenticated_client, SMALL_SOURCE)
    resp = authenticated_client.post("/api/v2/dsl/deground", json={"problem": problem})
    assert resp.status_code == 200, resp.text
    source = resp.json()["source"]
    assert source is not None
    assert "var x" in source
    # Honest by construction: the scalar draft recompiles to the same variable.
    recompiled = _compile(authenticated_client, source)
    assert [v["name"] for v in recompiled["variables"]] == ["x"]


@pytest.mark.integration
def test_deground_requires_auth(client):
    resp = client.post("/api/v2/dsl/deground", json={"problem": {"variables": []}})
    assert resp.status_code in (401, 403), resp.text
