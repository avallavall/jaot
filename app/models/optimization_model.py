"""Optimization Model definitions for the unified optimization platform.

This module defines the core models for the OptimizationModel system:
- ModelCatalog: Public marketplace of optimization models (official + community)
- OrganizationModel: Models activated/created by an organization
- ModelExecution: Execution history for models
- ModelReview: Reviews and ratings for models
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


class ModelCatalog(Base):
    """
    Public catalog of optimization models available in the marketplace.

    Models can be:
    - Official (created by JAOT, is_official=True)
    - Community (created by organizations and published)
    """

    __tablename__ = "model_catalog"

    # Primary Key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Basic Info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scenario_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Model Definition (for SCIP solver)
    generator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    example_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Versioning
    version: Mapped[str] = mapped_column(String(16), default="1.0.0")
    status: Mapped[str] = mapped_column(String(32), default="published", index=True)

    # Ownership & Origin
    author_organization_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_organization: Mapped[Organization | None] = relationship(
        "Organization",
        foreign_keys=[author_organization_id],
        lazy="noload",
    )
    is_official: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Pricing
    price_eur: Mapped[float] = mapped_column(Float, default=0.0)
    credits_per_execution: Mapped[int] = mapped_column(Integer, default=1)

    # Statistics
    total_activations: Mapped[int] = mapped_column(Integer, default=0)
    total_executions: Mapped[int] = mapped_column(Integer, default=0)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_model_catalog_category_status", "category", "status"),
        Index("ix_model_catalog_official_featured", "is_official", "is_featured"),
    )

    def __repr__(self) -> str:
        return f"<ModelCatalog(id={self.id}, name={self.name}, category={self.category})>"


class OrganizationModel(Base):
    """
    Optimization models that belong to an organization.

    These can be:
    - Activated from marketplace (catalog_id is set)
    - Created privately by the organization (catalog_id is NULL)
    """

    __tablename__ = "organization_models"

    # Primary Key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Ownership
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source (NULL = custom/private model)
    catalog_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("model_catalog.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Custom Configuration
    custom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # For private models (when catalog_id is NULL)
    private_definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    # Usage Stats
    total_executions: Mapped[int] = mapped_column(Integer, default=0)
    total_credits_used: Mapped[int] = mapped_column(Integer, default=0)
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Purchase Info
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    purchase_price_eur: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    catalog_model: Mapped["ModelCatalog | None"] = relationship(
        "ModelCatalog", foreign_keys=[catalog_id], lazy="joined"
    )

    __table_args__ = (
        Index("ix_org_model_org_active", "organization_id", "is_active"),
        Index("ix_org_model_org_catalog", "organization_id", "catalog_id"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationModel(id={self.id}, org={self.organization_id}, catalog={self.catalog_id})>"

    @property
    def display_name(self) -> str:
        """Get the display name (custom or from catalog)."""
        if self.custom_name:
            return self.custom_name
        if self.catalog_model:
            return self.catalog_model.display_name
        if self.private_definition:
            return str(self.private_definition.get("name", "Custom Model"))
        return "Unknown Model"


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
    organization_model_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("organization_models.id", ondelete="CASCADE"),
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

    # Credits
    credits_consumed: Mapped[int] = mapped_column(Integer, default=0)
    credits_base: Mapped[int] = mapped_column(Integer, default=1)
    credits_compute: Mapped[int] = mapped_column(Integer, default=0)

    # Trigger / origin tracking
    origin: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    trigger_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    # Async execution tracking
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    progress_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    organization_model: Mapped["OrganizationModel | None"] = relationship(
        "OrganizationModel", foreign_keys=[organization_model_id], lazy="joined"
    )

    __table_args__ = (
        Index("ix_model_exec_org_created", "organization_id", "created_at"),
        Index("ix_model_exec_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelExecution(id={self.id}, status={self.status}, credits={self.credits_consumed})>"
        )


class ModelReview(Base):
    """
    Reviews and ratings for models in the catalog.

    Only users who have executed a model can leave a review.
    """

    __tablename__ = "model_reviews"

    # Primary Key
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # What is being reviewed
    catalog_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False, index=True
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

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
    catalog_model: Mapped[ModelCatalog | None] = relationship(
        "ModelCatalog",
        foreign_keys=[catalog_id],
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_model_review_catalog_rating", "catalog_id", "rating"),
        Index("ix_model_review_user_catalog", "user_id", "catalog_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ModelReview(id={self.id}, catalog={self.catalog_id}, rating={self.rating})>"
