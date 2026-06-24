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

# Credits
from app.schemas.credits import (
    AllRatesResponse,
    CreditAdjustment,
    CreditBalanceResponse,
    CurrencyRequest,
    ExchangeRateResponse,
    ScheduleRequest,
    ScheduleResponse,
    TransactionListResponse,
    TransactionResponse,
    WithdrawalRequest,
    WithdrawalResponse,
)

# Health
from app.schemas.health import (
    HealthResponse,
    MetricsResponse,
    SystemMetrics,
)

# Optimization Models
from app.schemas.model import (
    ActivateModelRequest,
    AsyncExecutionResponse,
    CreatePrivateModelRequest,
    ExecuteModelRequest,
    ExecutionListResponse,
    ExecutionStatusResponse,
    FavoriteResponse,
    ModelCatalogListResponse,
    ModelCatalogResponse,
    ModelExecutionResponse,
    OrganizationModelListResponse,
    OrganizationModelResponse,
    PublishModelRequest,
    ReviewCreate,
    ReviewListResponse,
    ReviewResponse,
    UpdateModelRequest,
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
    "OrganizationModelResponse",
    "OrganizationModelListResponse",
    "ActivateModelRequest",
    "CreatePrivateModelRequest",
    "UpdateModelRequest",
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
    "ExchangeRateResponse",
    "AllRatesResponse",
    "CreditBalanceResponse",
    "TransactionResponse",
    "TransactionListResponse",
    "WithdrawalRequest",
    "WithdrawalResponse",
    "ScheduleRequest",
    "ScheduleResponse",
    "CurrencyRequest",
    "CreditAdjustment",
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
