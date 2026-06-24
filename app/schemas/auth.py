"""Authentication schemas.

Contains both API-key-based and email/password-based auth schemas.
"""

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    """Login request schema (API key based)."""

    api_key: str


class LoginResponse(BaseModel):
    """Login response with user and org info."""

    success: bool
    user: dict[str, Any]
    organization: dict[str, Any]
    permissions: dict[str, Any]


class SignupRequest(BaseModel):
    """User signup request (API key flow)."""

    email: EmailStr
    name: str = Field(..., min_length=2)
    organization_name: str = Field(..., min_length=2)
    # Self-serve signup only grants the free tier — paid plans require Stripe checkout or an
    # admin. Accepting them here handed out paid quotas/credits with no payment step.
    plan: Literal["free"] = Field(default="free")


class SignupResponse(BaseModel):
    """Signup response."""

    user_id: str
    organization_id: str
    api_key: str
    credits_balance: int
    plan: str
    message: str


class PlanLimitsResponse(BaseModel):
    """Plan tier limits exposed to the frontend."""

    max_variables: int
    max_solve_time_seconds: int
    max_daily_solves: int
    allowed_features: list[str]


class MeResponse(BaseModel):
    """Current user info response."""

    user_id: str
    user_name: str
    user_email: str | None
    organization_id: str
    organization_name: str
    plan: str
    credits_balance: int
    is_admin: bool
    # READ-ONLY signal derived server-side from Organization.owner_user_id == user.id.
    # FE uses this for UI gating (mutating controls); actual authorization checks
    # remain server-side on OrgOwnerUser dep (app/api/deps.py). Default False is
    # the safe choice so callers that receive a response without this field
    # (e.g. old cached responses) never silently gain owner privileges. (D-7.1-06)
    is_org_owner: bool = False
    can_build_plugins: bool
    skill_level: str = "beginner"
    guidance_state: dict[str, Any] | None = None
    email_verified: bool = False
    plan_limits: PlanLimitsResponse | None = None


class TokenPayload(BaseModel):
    """JWT token payload (for future use)."""

    sub: str  # user_id
    org: str  # organization_id
    admin: bool = False
    exp: int | None = None


class EmailLoginRequest(BaseModel):
    """Email login request."""

    email: EmailStr
    password: str
    remember_me: bool = False


class EmailSignupRequest(BaseModel):
    """Email signup with password."""

    email: EmailStr
    name: str = Field(..., min_length=2)
    organization_name: str = Field(..., min_length=2)
    # Same free-tier-only rule as SignupRequest (see comment there).
    plan: Literal["free"] = Field(default="free")
    password: str = Field(..., min_length=12)
    confirm_password: str = Field(..., min_length=12)
    tos_accepted: bool = Field(default=False)

    @model_validator(mode="after")
    def passwords_match(self) -> "EmailSignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class EmailSignupResponse(BaseModel):
    """Email signup response."""

    user_id: str
    organization_id: str
    api_key: str
    credits_balance: int
    plan: str
    message: str
    email_verified: bool


class ForgotPasswordRequest(BaseModel):
    """Forgot password request."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request."""

    token: str
    password: str = Field(..., min_length=12)


class VerifyEmailRequest(BaseModel):
    """Email verification request."""

    token: str


class TokenRefreshResponse(BaseModel):
    """Token refresh response."""

    success: bool
    message: str


class AuthTokenResponse(BaseModel):
    """Auth token response (login/signup with email)."""

    success: bool
    user: dict[str, Any]
    organization: dict[str, Any]
    permissions: dict[str, Any]
    email_verified: bool
