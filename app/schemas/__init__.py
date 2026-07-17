"""Pydantic schemas for API requests and responses."""

# Common
# API Keys
from app.schemas.api_key import (
    APIKeyInfo,
    CreateKeyRequest,
    CreateKeyResponse,
    KeyListResponse,
)

# Auth
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    SignupRequest,
    SignupResponse,
    TokenPayload,
)
from app.schemas.common import (
    ErrorResponse,
    PaginatedResponse,
    SuccessResponse,
    TimestampMixin,
)

# Health
from app.schemas.health import (
    HealthResponse,
    MetricsResponse,
    SystemMetrics,
)

# Optimization Models
from app.schemas.model import (
    AsyncExecutionResponse,
    ExecuteModelRequest,
    ExecutionListResponse,
    ExecutionStatusResponse,
    FavoriteResponse,
    ModelCatalogListResponse,
    ModelCatalogResponse,
    ModelExecutionResponse,
    PublishModelRequest,
    ReviewCreate,
    ReviewListResponse,
    ReviewResponse,
)

# Optimization (solver)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableSolution,
    VariableType,
)

# Organization
from app.schemas.organization import (
    OrganizationBase,
    OrganizationCreate,
    OrganizationPublicProfile,
    OrganizationResponse,
    OrganizationUpdate,
)

# User
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserPublicProfile,
    UserResponse,
    UserUpdate,
)

__all__ = [
    # Common
    "PaginatedResponse",
    "SuccessResponse",
    "ErrorResponse",
    "TimestampMixin",
    # Auth
    "LoginRequest",
    "LoginResponse",
    "SignupRequest",
    "SignupResponse",
    "MeResponse",
    "TokenPayload",
    # Organization
    "OrganizationBase",
    "OrganizationCreate",
    "OrganizationUpdate",
    "OrganizationResponse",
    "OrganizationPublicProfile",
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserPublicProfile",
    # Models
    "ModelCatalogResponse",
    "ModelCatalogListResponse",
    "PublishModelRequest",
    "ExecuteModelRequest",
    "ModelExecutionResponse",
    "ExecutionListResponse",
    "AsyncExecutionResponse",
    "ExecutionStatusResponse",
    "FavoriteResponse",
    "ReviewCreate",
    "ReviewResponse",
    "ReviewListResponse",
    # Credits
    # API Keys
    "CreateKeyRequest",
    "APIKeyInfo",
    "CreateKeyResponse",
    "KeyListResponse",
    # Health
    "SystemMetrics",
    "HealthResponse",
    "MetricsResponse",
    # Optimization
    "OptimizationProblem",
    "OptimizationResult",
    "Variable",
    "VariableType",
    "Constraint",
    "Objective",
    "ObjectiveSense",
    "SolverStatus",
    "SolverOptions",
    "VariableSolution",
]
