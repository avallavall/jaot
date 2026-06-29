"""ModelProject — the first-class identity that owns a model's lifecycle + versions.

The model itself (the solver-agnostic OptimizationProblem) is the protagonist;
the canvas and DSL source are co-stored representations of it. Each project has a
mutable HEAD ``draft_*`` block (the working tree, exactly one per project) and an
append-only list of immutable, commit-grade ``ModelProjectVersion`` snapshots.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

if TYPE_CHECKING:
    from app.models.user import User


def _default_project_id() -> str:
    return generate_id("mp_")


def _default_version_id() -> str:
    return generate_id("mpv_")


class ModelProject(Base):
    """A first-class optimization model project (git working-tree analogy).

    The ``draft_*`` columns are the single mutable working draft; committed,
    immutable snapshots live in ``model_project_versions``. ``current_version_id``
    points at the latest committed version (app-enforced — no FK, which would be
    circular with the versions table).
    """

    __tablename__ = "model_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_project_id)
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # First model entity to carry workspace scoping at rest (builder docs never did).
    workspace_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled Project")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | archived (soft-delete via status + archived_at)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)

    # How the project was SEEDED (provenance of the project itself):
    # blank | template | marketplace | import | llm_conversation | builder_document
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Committed HEAD pointer. App-enforced (no FK — circular with versions).
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    committed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Mutable working draft (exactly one per project) ---
    draft_model_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    draft_canvas_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    draft_dsl_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Optimistic-concurrency token for the HEAD draft (If-Match); bumped on every write.
    draft_lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    versions: Mapped[list["ModelProjectVersion"]] = relationship(
        "ModelProjectVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ModelProjectVersion.sequence",
    )
    # Who created the project — surfaced as an attribution badge in the list. The
    # list is org-wide (collaborative), so "by {name}" tells whose model it is.
    # ``selectin`` (a separate batched query), NOT ``joined``: a joined eager load
    # turns the ``SELECT ... FOR UPDATE`` lock in commit into an outer join, which
    # Postgres rejects ("FOR UPDATE cannot be applied to the nullable side").
    creator: Mapped["User | None"] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )

    __table_args__ = (
        Index("ix_model_projects_org_status", "organization_id", "status"),
        Index("ix_model_projects_org_updated", "organization_id", "updated_at"),
    )

    @property
    def created_by_name(self) -> str | None:
        """Display name of the creator (None if the user was deleted)."""
        return self.creator.name if self.creator else None

    def __repr__(self) -> str:
        return f"<ModelProject(id={self.id!r}, name={self.name!r}, status={self.status!r})>"


class ModelProjectVersion(Base):
    """An immutable, commit-style snapshot of a ModelProject at a point in time.

    A version captures all three representations (model_json / canvas_json /
    dsl_source) plus a content hash and commit metadata. There is deliberately
    no ``updated_at`` and the service exposes no UPDATE path — past versions are
    never mutated (restore copies a snapshot into the draft, leaving history
    intact).
    """

    __tablename__ = "model_project_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_version_id)
    model_project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalized so multi-tenant filtering needs no join to the project.
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Monotonic per project (v1, v2, …). Allocated under FOR UPDATE on the project row.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Lineage / future branching. App-enforced (no self-FK → avoids use_alter ordering).
    parent_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Canonical snapshot (full, not diff) ---
    model_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    canvas_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dsl_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # --- Commit metadata ---
    commit_summary: Mapped[str] = mapped_column(String(500), nullable=False)  # REQUIRED subject
    commit_body: Mapped[str | None] = mapped_column(Text, nullable=True)  # optional "why"
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Cached analysis (populated at commit in P1b; immutable thereafter) ---
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    problem_class: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )

    project: Mapped["ModelProject"] = relationship("ModelProject", back_populates="versions")

    __table_args__ = (
        Index("ix_mpv_project_sequence", "model_project_id", "sequence", unique=True),
        Index("ix_mpv_org_created", "organization_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelProjectVersion(id={self.id!r}, project={self.model_project_id!r}, "
            f"sequence={self.sequence})>"
        )
