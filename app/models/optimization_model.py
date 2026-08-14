"""Optimization Model definitions for the unified optimization platform.

This module defines the core models for the OptimizationModel system:
- ModelExecution: Execution history for models
- ModelReview: Reviews and ratings for models

The pre-fusion pair ``ModelCatalog`` (public marketplace) and ``OrganizationModel``
(an org's activated copy) was retired by D-26: ``ModelProject`` owns a model's
lifecycle and ``ModelProjectListing`` is its marketplace facet.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class ModelCategory(str, Enum):
    """Categories for optimization models."""

    # Original categories
    FINANCE = "finance"
    LOGISTICS = "logistics"
    MANUFACTURING = "manufacturing"
    AGRICULTURE = "agriculture"
    HEALTHCARE = "healthcare"
    ENERGY = "energy"
    RETAIL = "retail"
    HR = "hr"
    GENERAL = "general"
    # Expanded categories (phase 44)
    SUPPLY_CHAIN = "supply_chain"
    FACILITY_LOCATION = "facility_location"
    NETWORK_GRAPH = "network_graph"
    CUTTING_PACKING = "cutting_packing"
    TELECOM = "telecom"
    TRANSPORTATION = "transportation"
    ENVIRONMENTAL = "environmental"
    SPORTS = "sports"
    EDUCATION = "education"
    REAL_ESTATE = "real_estate"
    MINING = "mining"
    WATER_MANAGEMENT = "water_management"
    AEROSPACE = "aerospace"
    PHARMACEUTICAL = "pharmaceutical"
    CHEMICAL_ENGINEERING = "chemical_engineering"
    FORESTRY = "forestry"
    MARITIME = "maritime"
    RAILWAY = "railway"
    FOOD_BEVERAGE = "food_beverage"
    TEXTILE = "textile"
    CONSTRUCTION = "construction"
    ADVERTISING_MEDIA = "advertising_media"
    WAREHOUSE = "warehouse"
    INSURANCE = "insurance"
    GOVERNMENT = "government"


class ModelStatus(str, Enum):
    """Status of a model in the catalog."""

    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ExecutionStatus(str, Enum):
    """Status of a model execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ModelExecution(Base):
    """
    Execution history for optimization models.

    Records every time a model is executed, including input, output,
    performance metrics, and credit consumption.
    """

    __tablename__ = "model_executions"

    # Primary Key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # References
    # Historic provenance for runs that predate the P1.5 fusion (D-26). The
    # ``organization_models`` table it pointed at is gone, so this is now an
    # opaque id like source_id — kept, not dropped, because it is the only
    # model identity those old runs have: the GDPR export falls back to it,
    # platform analytics separates legacy from project runs by it, and the
    # execution detail endpoint returns it.
    organization_model_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    executed_by_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Execution Data
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Results
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Performance
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    solver_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Solver identity — which adapter processed this execution
    solver_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Auto-routing decision telemetry (Phase 7.4 / D-13 / INT-01).
    # Slugs from app/domains/solver/services/auto_router.py:
    # lp_routed_to_highs | quadratic_routed_to_hexaly |
    # milp_routed_to_scip | hexaly_unavailable_fallback. Nullable — solves
    # with explicit solver_name (no auto-routing) leave this NULL.
    # DB column added by Plan 09 migration; ORM declaration is harmless until then.
    auto_route_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Provenance — how the execution was created and what it traces back to.
    # origin values: visual_builder | ai_builder | template | import |
    #   marketplace | trigger | api | mcp | manual (legacy default).
    # Widened 16->32 to fit the richer slugs (additive: VARCHAR grow is safe).
    origin: Mapped[str] = mapped_column(String(32), default="manual", server_default="manual")
    trigger_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # source_kind/source_id: the object this execution can navigate back to.
    # Generic (not an FK) because builder_document / llm_conversation / template
    # have no dedicated FK on this table. Kinds: builder_document |
    # llm_conversation | template | organization_model | trigger | imported_file.
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Per-project history (P1a): the ModelProject + committed version this run
    # came from (NULL for non-project solves). The generic source_kind/source_id
    # above also carry the "model_project" provenance for the "open origin"
    # navigation; these typed columns power fast per-project history queries.
    model_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_project_version_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Dataset provenance (§8 Scenarios / S1): which named dataset the model was
    # compiled against for this run. `dataset_name` is a SNAPSHOT — datasets are
    # hard-deletable working data, and history must survive their deletion.
    # Not an FK on purpose (same rationale as source_kind/source_id above).
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Solver comparison (Phase 1 of the comparer): the parent run this execution
    # is one column of. NULL for every ordinary solve, which is nearly all of
    # them. A real FK, unlike source_kind/source_id above, because the parent is
    # one known table and a comparison must never keep a dangling child: the
    # cascade deletes the columns with the comparison, which is also how an
    # uploaded throwaway problem gets cleaned up.
    comparison_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("solver_comparisons.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Async execution tracking
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    progress_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)

    # What-if analysis by re-solves (Sensitivity L2) — the batch is expensive
    # (one full solve per scenario), so it is requested on demand and its result
    # is cached here rather than recomputed on every page view. Holds the JOB
    # envelope, not just the answer: {status, task_id, requested_at,
    # completed_at, error, result}. Its own column instead of a key inside
    # result_data so an analysis can never race the solve writer for that blob.
    scenario_analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_model_exec_org_created", "organization_id", "created_at"),
        Index("ix_model_exec_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ModelExecution(id={self.id}, status={self.status})>"


class ModelReview(Base):
    """
    Reviews and ratings for models in the catalog.

    Only users who have executed a model can leave a review.
    """

    __tablename__ = "model_reviews"

    # Primary Key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # What is being reviewed. P1.5 fusion: reviews are keyed on the unified Model.
    model_project_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("model_projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Who is reviewing
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Review content
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Moderation
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    is_reported: Mapped[bool] = mapped_column(Boolean, default=False)
    report_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships (lazy="noload" — use explicit joinedload/batch pre-fetch)
    reviewer_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="noload",
    )
    reviewer_organization: Mapped[Organization | None] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        lazy="noload",
    )
    __table_args__ = (
        Index("ix_model_review_project_rating", "model_project_id", "rating"),
        # One review per user per model — enforced by the database, not just by
        # the read-then-write check in create_review (D-26).
        #
        # This replaces a unique index on (user_id, catalog_id) that had quietly
        # stopped protecting anything: since the P1.5 fusion every new review
        # leaves catalog_id NULL, and Postgres does not consider two NULLs equal,
        # so the index admitted unlimited duplicates. Two concurrent POSTs could
        # both pass the existence check and both insert.
        Index("ix_model_review_user_project", "user_id", "model_project_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ModelReview(id={self.id}, model={self.model_project_id}, rating={self.rating})>"
