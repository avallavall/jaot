"""Solver comparison — one problem, several solvers, identical conditions.

A ``SolverComparison`` is the parent of N ``ModelExecution`` rows, one per solver
asked for. It exists because the comparison needs something the children cannot
carry: the settings every child was given, and the guarantee that all of them
received the SAME ones. Read a child's ``input_data`` on its own and you cannot
tell whether the run next to it got the same time limit.

The problem is snapshotted here at creation. Every child then solves that exact
snapshot, so a model edited mid-comparison cannot make two columns describe two
different problems. The snapshot is also what makes an uploaded file work: the
upload is throwaway (owner decision, 2026-08-14) and lives only in this row, so
deleting the comparison deletes the problem with it.

The snapshot lives here and nowhere else. Each child used to store it again in
its own ``input_data``, which multiplied it by the number of solvers asked for:
3.8 MB as JSON on an assignment model of 22,500 binary variables, so one matrix
row of four solvers wrote about 19 MB of the same bytes. Consumers read
``ModelExecution.problem_data``, which falls back to this row — never
``input_data`` directly. Rows written before that keep their own copy and it is
still what they return.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class ComparisonStatus(str, Enum):
    """Status of a solver comparison run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Where the compared problem came from. ``uploaded_file`` problems live only in
#: this row and die with it; ``model_project`` ones snapshot a studio model.
COMPARISON_SOURCE_KINDS = frozenset({"model_project", "uploaded_file"})

#: Default thread count for a comparison run.
#:
#: NOT 0 ("auto"). Auto means a different thing per solver: on Linux HiGHS lets
#: the library decide while SCIP applies its own default, so two columns of the
#: table would be measuring different machines. One thread each is the only
#: setting that is demonstrably equal for everyone, and it is what a solver
#: comparison is normally run at. The user can raise it; the value used is
#: recorded on the row and shown above the table.
DEFAULT_COMPARISON_THREADS = 1


class SolverComparison(Base):
    """One problem run against several solvers under identical settings."""

    __tablename__ = "solver_comparisons"

    # Primary key — prefixed id, "cmp_".
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ── What is being compared ────────────────────────────────────────────
    # The snapshot every child solves, held only here. See the module docstring.
    #
    # Empty until the worker has compiled it, and only ever for a matrix row. A
    # matrix compiles one problem per dataset, and doing that inside the launch
    # request put the whole cost of the model in front of the user — 28 seconds
    # and 57 MB for three datasets of 22,500 variables. The row is created first
    # and its worker fills this in. A single comparison arrives with its snapshot
    # already in hand and never passes through the empty state.
    problem_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: The name to SHOW for this comparison: the studio model's name, or the
    #: uploaded file's, falling back to the name inside the problem. That last
    #: one is often an exporter's leftover — real models in the wild carry "obj".
    problem_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What the compared problem is. Twelve seconds means one thing on an LP and
    # another on a mixed-integer model with twenty thousand rows, so the table
    # says which it was. Written once at creation and never derived on read: the
    # class needs every constraint parsed, and the page polls while it runs.
    problem_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    variable_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    constraint_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Provenance. Generic (not an FK) for the same reason ModelExecution's
    # source_kind/source_id are: an uploaded file has no table to point at.
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Name of the file the user dropped in, for the header. The file itself is
    # never kept — only the parsed problem above.
    uploaded_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Typed studio provenance. Phase 3 crosses several datasets with several
    # solvers; a comparison then names the dataset its snapshot was compiled
    # against. dataset_name is a snapshot too, so history survives its deletion.
    model_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_project_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Batch membership ──────────────────────────────────────────────────
    # A matrix run is N comparisons that share this id, one per dataset. There is
    # no batch table on purpose: a batch holds no state its members do not
    # already carry, and a parent row would need its status kept in step with
    # theirs on every write. ``batch_position`` keeps the rows in the order the
    # user picked them, which is also the order they run in.
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── The settings every solver received ────────────────────────────────
    # These are the whole point of the parent row. Without them a reader cannot
    # know the table is a fair comparison, and a table nobody can trust is worse
    # than no table.
    time_limit_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    gap_tolerance: Mapped[float] = mapped_column(Float, nullable=False)
    threads: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_COMPARISON_THREADS
    )
    # No seed column: SolverOptions has no seed field, so no adapter can be told
    # to be deterministic today. Adding the column would let the UI claim a
    # guarantee the solvers never received. See TECH_DEBT if this changes.

    # Solvers asked for, in the order they will run. A list of lowercase adapter
    # names, e.g. ["scip", "highs"].
    solver_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # ── Run state ─────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ComparisonStatus.PENDING.value, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Which worker ran it. Times are only comparable within one comparison on
    # one machine, so the machine is shown next to them rather than left implicit.
    machine_note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_solver_comparisons_org_created", "organization_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<SolverComparison(id={self.id}, status={self.status})>"
