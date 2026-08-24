"""ModelProject — the first-class identity that owns a model's lifecycle + versions.

The model itself (the solver-agnostic OptimizationProblem) is the protagonist;
the canvas and DSL source are co-stored representations of it. Each project has a
mutable HEAD ``draft_*`` block (the working tree, exactly one per project) and an
append-only list of immutable, commit-grade ``ModelProjectVersion`` snapshots.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
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


def _default_dataset_id() -> str:
    return generate_id("mpd_")


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
    )
    # First model entity to carry workspace scoping at rest (builder docs never did).
    # Filtered only in combination with organization_id, which is indexed, so no
    # separate index (kept aligned with the migration — the org filter carries it).
    workspace_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled Project")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | archived (soft-delete via status + archived_at); served by the
    # (organization_id, status) composite index below.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

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
    draft_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Optimistic-concurrency token for the HEAD draft (If-Match); bumped on every write.
    draft_lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list["ModelProjectVersion"]] = relationship(
        "ModelProjectVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ModelProjectVersion.sequence",
    )
    datasets: Mapped[list["ModelProjectDataset"]] = relationship(
        "ModelProjectDataset",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ModelProjectDataset.created_at",
    )
    # Who created the project — surfaced as an attribution badge in the list. The
    # list is org-wide (collaborative), so "by {name}" tells whose model it is.
    # ``selectin`` (a separate batched query), NOT ``joined``: a joined eager load
    # turns the ``SELECT ... FOR UPDATE`` lock in commit into an outer join, which
    # Postgres rejects ("FOR UPDATE cannot be applied to the nullable side").
    creator: Mapped["User | None"] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )

    # Index names mirror the migration (20260629_add_model_projects) exactly so
    # `alembic --autogenerate` stays a no-op for this table.
    __table_args__ = (
        Index("ix_model_projects_organization_id", "organization_id"),
        Index("ix_model_projects_org_status", "organization_id", "status"),
        Index("ix_model_projects_org_updated", "organization_id", "updated_at"),
        # Adoptions are counted off these rows on every public marketplace
        # request — the catalogue list, a model page, an author profile. The
        # count joins `source_ref` to the listing id and filters `source_type`,
        # and without this it is a sequential scan of every project on the
        # platform on an unauthenticated route.
        Index("ix_model_projects_source", "source_type", "source_ref"),
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
    )
    # Denormalized so multi-tenant filtering needs no join to the project; served by
    # the (organization_id, created_at) composite index below.
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Monotonic per project (v1, v2, …). Allocated under FOR UPDATE on the project row.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Lineage / future branching. App-enforced (no self-FK → avoids use_alter ordering).
    parent_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Canonical snapshot (full, not diff) ---
    model_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    canvas_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dsl_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

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
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["ModelProject"] = relationship("ModelProject", back_populates="versions")

    # Index names mirror the migration (20260629_add_model_projects) exactly so
    # `alembic --autogenerate` stays a no-op for this table.
    __table_args__ = (
        Index("ix_mpv_project", "model_project_id"),
        Index("ix_mpv_project_sequence", "model_project_id", "sequence", unique=True),
        Index("ix_mpv_org_created", "organization_id", "created_at"),
        Index("ix_mpv_content_hash", "content_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelProjectVersion(id={self.id!r}, project={self.model_project_id!r}, "
            f"sequence={self.sequence})>"
        )


class ModelProjectDataset(Base):
    """A named data bundle — a "scenario" — for a project's parametric JModel source.

    Holds the set members + param values (``data_json``, the ``JModelData`` JSON
    shape: ``{"sets": {...}, "params": {...}}``) that fill a declaration-only JModel
    at compile time. One model, many datasets is the §8 Scenarios seam (the TFM case:
    16 scenarios = 1 model + 16 data bundles). Datasets are draft-level working data,
    deliberately NOT snapshotted into versions — a version freezes the model's
    structure; the data varies per run.
    """

    __tablename__ = "model_project_datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_dataset_id)
    model_project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized so multi-tenant filtering needs no join to the project (same
    # rationale as ModelProjectVersion.organization_id).
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Validated as JModelData (shape + members/values) on every write.
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    project: Mapped["ModelProject"] = relationship("ModelProject", back_populates="datasets")

    # Index names mirror the migration (20260703_add_model_project_datasets) exactly
    # so `alembic --autogenerate` stays a no-op for this table.
    __table_args__ = (
        Index("ix_mpd_project", "model_project_id"),
        Index("ix_mpd_project_name", "model_project_id", "name", unique=True),
        Index("ix_mpd_org", "organization_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelProjectDataset(id={self.id!r}, project={self.model_project_id!r}, "
            f"name={self.name!r})>"
        )


class ModelProjectListing(Base):
    """The marketplace FACET of a ModelProject (P1.5 fusion, D4).

    A 1:1 extension keyed by the project id: "publishing to the marketplace"
    attaches ONE of these (the listing presentation + the generator facet that
    parametric officials execute through) instead of copying the model into a
    separate ``model_catalog`` row. The model CONTENT lives only in the
    project/version; this table holds only the marketplace-specific presentation +
    rollups. Columns mirror the surviving ``ModelCatalog`` columns so the F3
    backfill is a near-direct copy (``generator_type`` and friends are nullable
    here because a plain published project has no generator — it runs from its
    versioned problem).
    """

    __tablename__ = "model_project_listings"

    # PK == FK: exactly one listing per project, sharing its id.
    model_project_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_projects.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Basic listing info (marketplace presentation; may differ from the project name)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scenario_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Generator facet — parametric officials execute via generate(inputs); a plain
    # published project leaves these null and runs from its versioned problem.
    generator_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    input_fields: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    example_input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Versioning + publication status.
    # Lifecycle: draft -> published -> unpublished (and back). Withdrawing keeps
    # the row and its rollups; every catalog surface filters status == "published",
    # so an unpublished listing is simply absent from all of them.
    version: Mapped[str] = mapped_column(String(16), default="1.0.0")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    # The committed version pinned as the public one (publish pins a version, never
    # the dirty draft). App-enforced link; SET NULL if the version is ever removed.
    pinned_version_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("model_project_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Ownership & origin
    author_organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_official: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Statistics (rollups mirrored from the catalog).
    #
    # There is no `total_activations` here. It was a stored counter bumped when
    # somebody forked the listing, and nothing ever recomputed it: on the
    # development database it read 66 against the 6 that `adoption_query`
    # counts, and the stored one was what a marketplace card showed. Adoptions
    # are counted off the fork rows now — see `adoption_counts`.
    total_executions: Mapped[int] = mapped_column(Integer, default=0)
    # Raw tallies the two derived figures below are computed from. Kept as
    # counters so concurrent workers can bump them in one atomic UPDATE — a
    # read-modify-write of the averages would lose increments under load.
    successful_executions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Counted apart from the successes: backfilled rows are successes without a
    # recorded duration, so they must not dilute the average.
    timed_executions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    avg_execution_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Visibility
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)

    # Media
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screenshot_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Rich description sections — markdown stored as text
    section_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_features: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_how_it_works: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_example_io: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_changelog: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Index names mirror the migration (20260712_p15_listings) exactly so
    # `alembic --autogenerate` stays a no-op for this table.
    __table_args__ = (
        Index("ix_mpl_category_status", "category", "status"),
        Index("ix_mpl_official_featured", "is_official", "is_featured"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelProjectListing(project={self.model_project_id!r}, "
            f"status={self.status!r}, is_official={self.is_official})>"
        )
