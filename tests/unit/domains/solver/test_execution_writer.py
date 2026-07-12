"""Unit tests for the single ModelExecution writer (ADR-007 S3).

# CONTRACT-TEST: terminal-state-wins is enforced in exactly one place. No
automatic transition (worker completion, reaper failure, cancel) may overwrite a
row that already reached CANCELLED/COMPLETED/FAILED. These pin that guard so a
future edit to any writer call site cannot silently reintroduce the
"clobbered cancel / zombie completion" bug class.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domains.solver import execution_writer
from app.models import ExecutionStatus, ModelExecution
from app.schemas.optimization import OptimizationResult, SolverStatus

pytestmark = pytest.mark.unit


def _row(status: str = ExecutionStatus.PENDING.value) -> ModelExecution:
    return ModelExecution(
        id="exe_test",
        organization_id="org_test",
        status=status,
        input_data={},
    )


def _optimal_result() -> OptimizationResult:
    return OptimizationResult(
        status=SolverStatus.OPTIMAL,
        objective_value=42.0,
        solution={"x": 42.0},
        solve_time_seconds=0.25,
    )


class TestTerminalWins:
    @pytest.mark.parametrize(
        "terminal",
        [
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
        ],
    )
    def test_completed_does_not_overwrite_terminal(self, terminal: str) -> None:
        row = _row(terminal)
        applied = execution_writer.apply_completed(row, result=_optimal_result())
        assert applied is False
        assert row.status == terminal
        assert row.result_data is None  # untouched

    @pytest.mark.parametrize(
        "terminal",
        [
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
        ],
    )
    def test_failed_does_not_overwrite_terminal(self, terminal: str) -> None:
        row = _row(terminal)
        applied = execution_writer.apply_failed(row, error="boom")
        assert applied is False
        assert row.status == terminal

    def test_running_does_not_overwrite_terminal(self) -> None:
        row = _row(ExecutionStatus.COMPLETED.value)
        assert execution_writer.apply_running(row) is False
        assert row.status == ExecutionStatus.COMPLETED.value

    def test_cancel_wins_over_live_but_not_over_verdict(self) -> None:
        live = _row(ExecutionStatus.RUNNING.value)
        assert execution_writer.apply_cancelled(live) is True
        assert live.status == ExecutionStatus.CANCELLED.value

        done = _row(ExecutionStatus.COMPLETED.value)
        assert execution_writer.apply_cancelled(done) is False
        assert done.status == ExecutionStatus.COMPLETED.value


class TestCompleted:
    def test_records_result_fields(self) -> None:
        row = _row()
        applied = execution_writer.apply_completed(
            row,
            result=_optimal_result(),
            execution_time_seconds=1.5,
            solver_name="scip",
        )
        assert applied is True
        assert row.status == ExecutionStatus.COMPLETED.value
        assert row.solver_status == SolverStatus.OPTIMAL.value
        assert row.objective_value == 42.0
        assert row.execution_time_ms == 1500
        assert row.solver_name == "scip"
        # Credits are RECORDED, never deducted here (the ledger is elsewhere).
        assert row.completed_at is not None
        assert isinstance(row.result_data, dict)

    def test_running_stamps_started_at_once(self) -> None:
        row = _row()
        assert execution_writer.apply_running(row) is True
        assert row.status == ExecutionStatus.RUNNING.value
        first_started = row.started_at
        assert first_started is not None
        # A second running transition (redelivery) does not move started_at.
        execution_writer.apply_running(row)
        assert row.started_at == first_started


class TestFailed:
    def test_truncates_error_to_2000_chars(self) -> None:
        row = _row()
        applied = execution_writer.apply_failed(row, error="x" * 5000)
        assert applied is True
        assert row.status == ExecutionStatus.FAILED.value
        assert len(row.error_message) == 2000

    def test_preserve_completed_at_keeps_prior_stamp(self) -> None:
        from app.shared.utils.datetime_helpers import utcnow

        row = _row()
        stamp = utcnow()
        row.completed_at = stamp
        execution_writer.apply_failed(row, error="reaped", preserve_completed_at=True)
        assert row.completed_at == stamp


class TestCompletedFields:
    """The reaper reconciles from loose fields (no OptimizationResult object)."""

    def test_sets_status_and_clears_error(self) -> None:
        row = _row(ExecutionStatus.RUNNING.value)
        row.error_message = "stale"
        applied = execution_writer.apply_completed_fields(
            row, solver_status="optimal", objective_value=3.0
        )
        assert applied is True
        assert row.status == ExecutionStatus.COMPLETED.value
        assert row.error_message is None
        assert row.solver_status == "optimal"
        assert row.objective_value == 3.0

    def test_truncates_solver_status_to_32(self) -> None:
        row = _row(ExecutionStatus.RUNNING.value)
        execution_writer.apply_completed_fields(row, solver_status="s" * 100)
        assert len(row.solver_status) == 32

    def test_does_not_overwrite_terminal(self) -> None:
        row = _row(ExecutionStatus.FAILED.value)
        assert execution_writer.apply_completed_fields(row, solver_status="optimal") is False
        assert row.status == ExecutionStatus.FAILED.value


class TestDuckTypedResult:
    """apply_completed reads a result via duck typing, not a concrete class."""

    def test_accepts_minimal_duck_typed_result(self) -> None:
        row = _row()
        fake = SimpleNamespace(
            status=SimpleNamespace(value="feasible"),
            objective_value=9.0,
            to_result_data=lambda: {"solution": {"x": 1}},
        )
        assert execution_writer.apply_completed(row, result=fake) is True
        assert row.solver_status == "feasible"
        assert row.objective_value == 9.0
        assert row.result_data == {"solution": {"x": 1}}
