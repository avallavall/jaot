"""Tests for file export service and API endpoints.

Unit tests for FileExportService (MPS/LP/CIP/SOL/CSV/JSON generation),
and integration tests for GET /api/v2/solve/export/{execution_id}/{format}.
"""

import json
import os

import pytest

from app.domains.solver.services.file_export import (
    FileExportError,
    FileExportService,
)
from app.models import ModelExecution
from app.models.optimization_model import ExecutionStatus
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)
from app.shared.utils.id_generator import generate_id


def _simple_problem() -> OptimizationProblem:
    """A simple 3-variable LP for testing exports."""
    return OptimizationProblem(
        name="export_test",
        variables=[
            Variable(name="x1", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
            Variable(name="x2", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
            Variable(name="x3", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=5),
        ],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x1 + 2*x2 + 3*x3"),
        constraints=[
            Constraint(name="c1", expression="2*x1 + x2 + x3 <= 10"),
            Constraint(name="c2", expression="x1 + 3*x2 + x3 <= 8"),
        ],
    )


def _sample_result_data() -> dict:
    """Sample result_data as stored in ModelExecution."""
    return {
        "model": {"x1": 3.0, "x2": 0.0, "x3": 0.0},
        "solution": {"x1": 3.0, "x2": 0.0, "x3": 0.0},
        "objective_value": 3.0,
        "solver_status": "optimal",
        "solve_time_seconds": 0.01,
    }


def _create_test_execution(
    db_session,
    org_id: str,
    *,
    execution_id: str | None = None,
    status: str = ExecutionStatus.COMPLETED.value,
    input_data: dict | None = None,
    result_data: dict | None = None,
) -> ModelExecution:
    """Create a ModelExecution for testing."""
    exe = ModelExecution(
        id=execution_id or generate_id("exe_"),
        organization_id=org_id,
        input_data=_simple_problem().model_dump() if input_data is None else input_data,
        result_data=_sample_result_data() if result_data is None else result_data,
        status=status,
        credits_consumed=1,
        solver_status="optimal",
        objective_value=3.0,
    )
    db_session.add(exe)
    db_session.commit()
    return exe


# UNIT TESTS — FileExportService: Solver formats (MPS, LP, CIP)


class TestExportSolverFormats:
    """Test MPS/LP/CIP export via SCIP writeProblem."""

    def setup_method(self):
        self.service = FileExportService()
        self.problem = _simple_problem()

    def test_export_mps_creates_file(self):
        path = self.service.export_to_file(self.problem, "mps")
        try:
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_export_mps_contains_variables(self):
        path = self.service.export_to_file(self.problem, "mps")
        try:
            with open(path) as f:
                content = f.read()
            assert "x1" in content
            assert "x2" in content
            assert "x3" in content
        finally:
            os.unlink(path)

    def test_export_lp_creates_file(self):
        path = self.service.export_to_file(self.problem, "lp")
        try:
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_export_lp_contains_objective(self):
        path = self.service.export_to_file(self.problem, "lp")
        try:
            with open(path) as f:
                content = f.read().lower()
            assert "minimize" in content or "min" in content
        finally:
            os.unlink(path)

    def test_export_cip_creates_file(self):
        path = self.service.export_to_file(self.problem, "cip")
        try:
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_export_cip_contains_constraints(self):
        path = self.service.export_to_file(self.problem, "cip")
        try:
            with open(path) as f:
                content = f.read()
            assert "c1" in content
            assert "c2" in content
        finally:
            os.unlink(path)

    def test_reject_unsupported_format(self):
        with pytest.raises(FileExportError, match="only supports"):
            self.service.export_to_file(self.problem, "csv")


# UNIT TESTS — FileExportService: Text formats (SOL, CSV, JSON)


class TestExportSol:
    """Test SOL file generation."""

    def setup_method(self):
        self.service = FileExportService()
        self.problem = _simple_problem()
        self.result = _sample_result_data()

    def test_sol_contains_objective(self):
        content = self.service.export_solution_sol(self.problem, self.result)
        assert "objective value = 3.0" in content

    def test_sol_contains_all_variables(self):
        content = self.service.export_solution_sol(self.problem, self.result)
        assert "x1" in content
        assert "x2" in content
        assert "x3" in content

    def test_sol_variable_values(self):
        content = self.service.export_solution_sol(self.problem, self.result)
        assert "3.0" in content  # x1 = 3.0

    def test_sol_no_solution_raises(self):
        with pytest.raises(FileExportError, match="No solution"):
            self.service.export_solution_sol(self.problem, {})


class TestExportCsv:
    """Test CSV generation."""

    def setup_method(self):
        self.service = FileExportService()
        self.problem = _simple_problem()
        self.result = _sample_result_data()

    def test_csv_has_header(self):
        content = self.service.export_solution_csv(self.problem, self.result)
        lines = content.strip().split("\n")
        assert "variable_name" in lines[0]
        assert "type" in lines[0]
        assert "value" in lines[0]

    def test_csv_has_all_variables(self):
        content = self.service.export_solution_csv(self.problem, self.result)
        assert "x1" in content
        assert "x2" in content
        assert "x3" in content

    def test_csv_row_count(self):
        """Strengthened TA-03 (12.4 Plan 05 LOW, D-08 relaxation): structured content + edge.

        Before: count-only `len(lines) == 4` (T3).
        After: assert exact header columns AND first-data-row column values
        match the fixture. The empty-solution edge is already covered by
        test_csv_no_solution_raises; here we verify the all-variables row
        contract on a non-empty result.
        """
        content = self.service.export_solution_csv(self.problem, self.result)
        lines = content.strip().split("\n")

        # Header + 3 variables.
        assert len(lines) == 4, f"Expected 4 lines (header + 3 vars), got {len(lines)}"

        # Header columns match the schema declared in
        # app/domains/solver/services/file_export.py:167.
        expected_header_cols = [
            "variable_name",
            "type",
            "lower_bound",
            "upper_bound",
            "value",
        ]
        header_cols = [c.strip() for c in lines[0].split(",")]
        assert header_cols == expected_header_cols, (
            f"CSV header drifted: got {header_cols}, expected {expected_header_cols}"
        )

        # First data row (x1) matches the fixture exactly:
        # name=x1, type=continuous, lb=0, ub=5, value=3.0
        x1_cols = [c.strip() for c in lines[1].split(",")]
        assert x1_cols[0] == "x1", f"First-row name drifted: {x1_cols[0]!r}"
        assert x1_cols[1] == "continuous", f"First-row type drifted: {x1_cols[1]!r}"
        # Numeric fields may render as "0" or "0.0" depending on Variable type.
        assert x1_cols[2] in ("0", "0.0"), f"First-row lower_bound drifted: {x1_cols[2]!r}"
        assert x1_cols[3] in ("5", "5.0"), f"First-row upper_bound drifted: {x1_cols[3]!r}"
        assert x1_cols[4] in ("3.0", "3"), f"First-row value drifted: {x1_cols[4]!r}"

    def test_csv_no_solution_raises(self):
        with pytest.raises(FileExportError, match="No solution"):
            self.service.export_solution_csv(self.problem, {})


class TestExportJson:
    """Test JSON export."""

    def setup_method(self):
        self.service = FileExportService()
        self.problem = _simple_problem()
        self.result = _sample_result_data()

    def test_json_is_valid(self):
        content = self.service.export_json(self.problem, self.result)
        data = json.loads(content)
        assert "problem" in data
        assert "result" in data

    def test_json_problem_has_variables(self):
        content = self.service.export_json(self.problem, self.result)
        data = json.loads(content)
        assert len(data["problem"]["variables"]) == 3

    def test_json_result_has_objective(self):
        content = self.service.export_json(self.problem, self.result)
        data = json.loads(content)
        assert data["result"]["objective_value"] == 3.0

    def test_json_without_result(self):
        content = self.service.export_json(self.problem, None)
        data = json.loads(content)
        assert "problem" in data
        assert "result" not in data


class TestExportModelJson:
    """Test FLAT model export (no solve required) and its import round-trip."""

    def setup_method(self):
        self.service = FileExportService()
        self.problem = _simple_problem()

    def test_model_json_is_flat(self):
        """export_model_json emits a bare OptimizationProblem, not {problem,result}."""
        content = self.service.export_model_json(self.problem)
        data = json.loads(content)
        assert "problem" not in data
        assert "result" not in data
        assert len(data["variables"]) == 3
        assert data["name"] == "export_test"

    def test_model_export_formats_exclude_solution_only(self):
        from app.domains.solver.services.file_export import MODEL_EXPORT_FORMATS

        assert "json" in MODEL_EXPORT_FORMATS
        assert {"mps", "lp", "cip"} <= MODEL_EXPORT_FORMATS
        # sol/csv need a solution, so they must NOT be model-export formats.
        assert "sol" not in MODEL_EXPORT_FORMATS
        assert "csv" not in MODEL_EXPORT_FORMATS

    def test_export_model_then_import_roundtrip(self):
        # CONTRACT-TEST: export-model JSON imports back to an equivalent problem
        from app.domains.solver.services.file_import import FileImportService

        content = self.service.export_model_json(self.problem)
        reimported = FileImportService().import_from_file(content.encode("utf-8"), "model.json")

        assert reimported.name == self.problem.name
        assert sorted(v.name for v in reimported.variables) == ["x1", "x2", "x3"]
        assert len(reimported.constraints) == 2
        assert reimported.objective.sense == self.problem.objective.sense

    def test_export_model_mps_roundtrips_variables(self):
        """MPS export of a model (no solve) re-imports with the same variables."""
        from app.domains.solver.services.file_import import FileImportService

        path = self.service.export_to_file(self.problem, "mps")
        try:
            with open(path, "rb") as fh:
                reimported = FileImportService().import_from_file(fh.read(), "model.mps")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        assert sorted(v.name for v in reimported.variables) == ["x1", "x2", "x3"]


class TestExportEndpoint:
    """Integration tests for GET /api/v2/solve/export/{execution_id}/{format}."""

    def test_export_mps(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 200
        assert "x1" in resp.text
        assert resp.headers.get("content-type", "").startswith("application/x-mps")

    def test_export_lp(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/lp")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/x-lp")

    def test_export_cip(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/cip")
        assert resp.status_code == 200

    def test_export_sol(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/sol")
        assert resp.status_code == 200
        assert "objective value" in resp.text
        assert "x1" in resp.text

    def test_export_csv(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/csv")
        assert resp.status_code == 200
        assert "variable_name" in resp.text
        assert "x1" in resp.text

    def test_export_json(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/json")
        assert resp.status_code == 200
        data = resp.json()
        assert "problem" in data
        assert "result" in data

    def test_export_unsupported_format(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/xlsx")
        assert resp.status_code == 422

    def test_export_not_found(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/export/exe_nonexistent/mps")
        assert resp.status_code == 404

    def test_export_cross_org_returns_404(self, authenticated_client, db_session):
        """Org A must receive 404 when attempting to export Org B's execution.

        Tenant isolation is enforced by filtering ModelExecution on
        organization_id. Leaking another org's execution would be a P0 multi-
        tenancy breach. This test creates a fresh foreign org/execution so it
        does not depend on the order of test_organization/_2 fixtures.
        """
        from app.models import Organization
        from app.shared.utils.id_generator import generate_id

        foreign_org = Organization(
            id=generate_id("org_"),
            name="Foreign Corp",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(foreign_org)
        db_session.commit()

        foreign_exe = _create_test_execution(db_session, foreign_org.id)

        resp = authenticated_client.get(f"/api/v2/solve/export/{foreign_exe.id}/mps")
        assert resp.status_code == 404

    def test_export_no_auth(self, client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 401

    def test_export_content_disposition(self, authenticated_client, db_session, test_organization):
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/sol")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".sol" in cd

    def test_export_round_trip_mps(self, authenticated_client, db_session, test_organization):
        """Export MPS then re-import and verify same problem structure."""
        exe = _create_test_execution(db_session, test_organization.id)

        # Export
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 200
        mps_content = resp.content

        # Re-import via preview
        resp2 = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("exported.mps", mps_content, "application/octet-stream")},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["metadata"]["num_variables"] == 3
        assert data["metadata"]["num_constraints"] == 2

    def test_export_round_trip_lp(self, authenticated_client, db_session, test_organization):
        """Export LP then re-import and verify same problem structure."""
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/lp")
        assert resp.status_code == 200

        resp2 = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("exported.lp", resp.content, "application/octet-stream")},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["metadata"]["num_variables"] == 3
        assert data["metadata"]["num_constraints"] == 2


class TestExportEdgeCases:
    """Edge cases: MIP problems, failed executions, multi-tenancy, etc."""

    def test_export_mip_knapsack(self, authenticated_client, db_session, test_organization):
        """Export a MIP (binary) problem and verify variable types preserved."""
        mip_problem = OptimizationProblem(
            name="knapsack",
            variables=[
                Variable(name="x1", type=VariableType.BINARY),
                Variable(name="x2", type=VariableType.BINARY),
                Variable(name="x3", type=VariableType.BINARY),
            ],
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x1 + 4*x2 + 2*x3"),
            constraints=[
                Constraint(name="capacity", expression="2*x1 + 3*x2 + x3 <= 5"),
            ],
        )
        mip_result = {
            "model": {"x1": 1.0, "x2": 1.0, "x3": 0.0},
            "objective_value": 7.0,
            "solver_status": "optimal",
        }
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            input_data=mip_problem.model_dump(),
            result_data=mip_result,
        )

        # Export as MPS and re-import to verify binary types
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 200

        resp2 = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("knapsack.mps", resp.content, "application/octet-stream")},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["metadata"]["num_binary"] == 3

    def test_export_sol_binary_values(self, authenticated_client, db_session, test_organization):
        """SOL export of binary problem has correct 0/1 values."""
        mip_problem = OptimizationProblem(
            name="binary_sol",
            variables=[
                Variable(name="x1", type=VariableType.BINARY),
                Variable(name="x2", type=VariableType.BINARY),
            ],
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x1 + x2"),
            constraints=[Constraint(name="c1", expression="x1 + x2 <= 1")],
        )
        result = {"model": {"x1": 1.0, "x2": 0.0}, "objective_value": 1.0}
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            input_data=mip_problem.model_dump(),
            result_data=result,
        )

        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/sol")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        # Should have objective line, blank, x1 line, x2 line
        assert any("1.0" in line and "x1" in line for line in lines)
        assert any("0.0" in line and "x2" in line for line in lines)

    def test_export_failed_execution_sol_422(
        self, authenticated_client, db_session, test_organization
    ):
        """SOL export of a failed execution (no solution) returns 422."""
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            status=ExecutionStatus.FAILED.value,
            result_data={},
        )
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/sol")
        assert resp.status_code == 422
        assert "No solution" in resp.json()["detail"]

    def test_export_failed_execution_csv_422(
        self, authenticated_client, db_session, test_organization
    ):
        """CSV export of a failed execution (no solution) returns 422."""
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            status=ExecutionStatus.FAILED.value,
            result_data={},
        )
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/csv")
        assert resp.status_code == 422

    def test_export_failed_execution_mps_still_works(
        self, authenticated_client, db_session, test_organization
    ):
        """MPS export of a failed execution still works (exports the problem, not solution)."""
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            status=ExecutionStatus.FAILED.value,
            result_data={},
        )
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 200
        assert "x1" in resp.text

    def test_export_json_failed_has_empty_result(
        self, authenticated_client, db_session, test_organization
    ):
        """JSON export of a failed execution includes empty result object."""
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            status=ExecutionStatus.FAILED.value,
            result_data={},
        )
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/json")
        assert resp.status_code == 200
        data = resp.json()
        assert "problem" in data
        # Empty result_data is falsy, so "result" key won't be present
        assert "result" not in data

    def test_export_csv_has_utf8_bom(self, authenticated_client, db_session, test_organization):
        """CSV export starts with UTF-8 BOM for Excel compatibility."""
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/csv")
        assert resp.status_code == 200
        # UTF-8 BOM is EF BB BF
        assert resp.content[:3] == b"\xef\xbb\xbf"

    def test_export_mixed_variable_types(self, authenticated_client, db_session, test_organization):
        """Export a problem with mixed variable types (binary + integer + continuous)."""
        mixed = OptimizationProblem(
            name="mixed_types",
            variables=[
                Variable(name="b1", type=VariableType.BINARY),
                Variable(name="i1", type=VariableType.INTEGER, lower_bound=0, upper_bound=10),
                Variable(name="c1", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
            ],
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="b1 + i1 + c1"),
            constraints=[Constraint(name="total", expression="b1 + i1 + c1 <= 50")],
        )
        result = {"model": {"b1": 0.0, "i1": 5.0, "c1": 10.5}, "objective_value": 15.5}
        exe = _create_test_execution(
            db_session,
            test_organization.id,
            input_data=mixed.model_dump(),
            result_data=result,
        )

        # CSV should show all types
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/csv")
        assert resp.status_code == 200
        assert "binary" in resp.text
        assert "integer" in resp.text
        assert "continuous" in resp.text

    def test_export_case_insensitive_format(
        self, authenticated_client, db_session, test_organization
    ):
        """Format parameter should be case-insensitive."""
        exe = _create_test_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/MPS")
        assert resp.status_code == 200

    def test_export_no_input_data_422(self, authenticated_client, db_session, test_organization):
        """Execution with no stored input_data returns 422."""
        exe = ModelExecution(
            id=generate_id("exe_"),
            organization_id=test_organization.id,
            input_data={},
            result_data=_sample_result_data(),
            status=ExecutionStatus.COMPLETED.value,
            credits_consumed=1,
        )
        db_session.add(exe)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/solve/export/{exe.id}/mps")
        assert resp.status_code == 422
