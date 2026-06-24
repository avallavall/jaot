"""Auth endpoints for API v2.

Supports both API key auth (existing) and email/password auth (new).
"""

import logging
import secrets
from datetime import timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Organization, RefreshToken, User
from app.schemas.auth import (
    EmailLoginRequest,
    EmailSignupRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    PlanLimitsResponse,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
)
from app.services.auth import APIKeyService, JWTService, PasswordService
from app.services.auth.password_service import DUMMY_HASH
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.rate_limiter import check_rate_limit, check_rate_limit_hourly
from app.shared.db.base import get_db
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.request_helpers import get_client_ip

logger = logging.getLogger(__name__)


def _rate_limit_or_raise(key: str, limit_per_minute: int, limit_per_day: int) -> None:
    """Check rate limit and raise 429 if exceeded."""
    allowed, rate_info = check_rate_limit(key, limit_per_minute, limit_per_day)
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)


# Cookie security: derive from DEBUG setting (secure=True in production)
_cookie_secure = not settings.DEBUG

# Account lockout constants
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

router = APIRouter()


def get_current_user(request: Request) -> User:
    """Get the current authenticated user from request state.

    The AuthMiddleware validates the API key or JWT cookie and attaches
    the user to request.state.

    Raises:
        HTTPException 401 if user not authenticated
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a valid API key in Authorization header.",
        )
    return cast(User, user)


def get_current_organization(request: Request) -> Organization:
    """Get the current organization from request state."""
    org = getattr(request.state, "organization", None)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a valid API key in Authorization header.",
        )
    return cast(Organization, org)


def _set_auth_cookies(
    response: JSONResponse,
    access_token: str,
    refresh_token: str,
    remember_me: bool = False,
    db: Session | None = None,
) -> None:
    """Set httpOnly JWT cookies on the response."""
    # Access token: 30 minutes
    if db is not None:
        access_expire = PSS.get_int(db, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
    else:
        access_expire = 30  # safe default when no db
    response.set_cookie(
        key="jaot_access_token",
        value=access_token,
        httponly=True,
        secure=_cookie_secure,
        samesite="lax",
        path="/",
        max_age=access_expire * 60,
    )
    # Refresh token: scoped to refresh endpoint
    if db is not None:
        remember_days = PSS.get_int(db, "JWT_REFRESH_TOKEN_REMEMBER_DAYS")
        expire_days = PSS.get_int(db, "JWT_REFRESH_TOKEN_EXPIRE_DAYS")
    else:
        remember_days = 30  # safe default when no db
        expire_days = 7
    max_age = remember_days * 86400 if remember_me else expire_days * 86400
    response.set_cookie(
        key="jaot_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_cookie_secure,
        samesite="lax",
        path="/api/v2/auth",
        max_age=max_age,
    )


def _build_auth_response_data(user: User, org: Organization) -> dict[str, Any]:
    """Build the common auth response body."""
    return {
        "success": True,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": user.is_admin,
        },
        "organization": {
            "id": org.id,
            "name": org.name,
            "plan": org.plan,
            "credits_balance": org.credits_balance,
        },
        "permissions": {
            "can_build_plugins": user.can_build_plugins,
            "ai_builder_enabled": getattr(org, "ai_builder_enabled", False),
        },
        "email_verified": getattr(user, "email_verified", False),
    }


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Validate API key and return user/org info.

    Used by frontend to validate credentials and get initial state.
    """
    # Rate limit login by API key prefix to prevent brute force
    key_prefix = request.api_key[:12] if len(request.api_key) >= 12 else request.api_key
    _rate_limit_or_raise(f"login:{key_prefix}", limit_per_minute=10, limit_per_day=100)

    # Verify API key using the service
    result = APIKeyService.verify_key(db, request.api_key)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    api_key_record, user, org = result

    return LoginResponse(
        success=True,
        user={
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": user.is_admin,
        },
        organization={
            "id": org.id,
            "name": org.name,
            "plan": org.plan,
            "credits_balance": org.credits_balance,
        },
        permissions={
            "can_build_plugins": user.can_build_plugins,
            "ai_builder_enabled": org.ai_builder_enabled,
        },
    )


@router.post("/login/email")
async def login_email(
    body: EmailLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Authenticate with email and password.

    Returns JWT access/refresh cookies and user info.
    """
    # Rate limit by IP: 5 per minute, 100 per day
    client_ip = get_client_ip(request)
    _rate_limit_or_raise(f"login_ip:{client_ip}", limit_per_minute=5, limit_per_day=100)

    user = db.query(User).filter(User.email == body.email).first()

    # Check account lockout (before password verification)
    if user and user.locked_until and user.locked_until > utcnow().replace(tzinfo=None):
        minutes_left = (
            int((user.locked_until - utcnow().replace(tzinfo=None)).total_seconds() / 60) + 1
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked. Try again in {minutes_left} minutes.",
        )

    # Timing-safe: always verify password even if user not found
    if not user or not user.password_hash:
        PasswordService.verify_password("dummy", DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Verify password
    if not PasswordService.verify_password(body.password, user.password_hash):
        # Increment failed attempts
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = utcnow().replace(tzinfo=None) + timedelta(
                minutes=LOCKOUT_DURATION_MINUTES
            )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Reset lockout on successful login
    if user.failed_login_attempts > 0:
        user.failed_login_attempts = 0
        user.locked_until = None

    # Rehash if needed (parameter upgrade)
    if PasswordService.needs_rehash(user.password_hash):
        user.password_hash = PasswordService.hash_password(body.password)
        db.commit()

    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Organization not found",
        )

    access_token = JWTService.create_access_token(
        user_id=user.id,
        org_id=org.id,
        is_admin=user.is_admin,
        db=db,
    )
    refresh_token_str, jti = JWTService.create_refresh_token(
        user_id=user.id,
        remember_me=body.remember_me,
        db=db,
    )

    days = (
        PSS.get_int(db, "JWT_REFRESH_TOKEN_REMEMBER_DAYS")
        if body.remember_me
        else PSS.get_int(db, "JWT_REFRESH_TOKEN_EXPIRE_DAYS")
    )
    rt_record = RefreshToken(
        user_id=user.id,
        jti=jti,
        expires_at=utcnow().replace(tzinfo=None) + timedelta(days=days),
    )
    db.add(rt_record)
    db.commit()

    # Fire-and-forget: log login analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=user.id,
            org_id=user.organization_id,
            event_type=evt.USER_LOGIN,
            ip_address=client_ip,
            metadata={"method": "email"},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    response_data = _build_auth_response_data(user, org)
    response = JSONResponse(content=response_data)
    _set_auth_cookies(response, access_token, refresh_token_str, body.remember_me, db=db)

    return response


@router.post("/signup/email")
async def signup_email(
    body: EmailSignupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Create a new user with email and password.

    Returns JWT cookies, API key, and user info.
    """
    client_ip = get_client_ip(request)
    _rate_limit_or_raise(f"signup_ip:{client_ip}", limit_per_minute=3, limit_per_day=20)

    if not PSS.get_bool(db, "REGISTRATION_ENABLED"):
        raise HTTPException(
            status_code=503,
            detail=("Registration is currently disabled. Contact support@jaot.io for access."),
        )

    if not body.tos_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must accept the Terms of Service to create an account.",
        )

    existing_user = db.query(User).filter(User.email == body.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    plan_config = PSS.get_plan_config_dynamic(db, body.plan)

    password_hash = PasswordService.hash_password(body.password)

    org_prefix = PSS.get_str(db, "ID_PREFIX_ORGANIZATION")
    org_id = f"{org_prefix}{secrets.token_hex(8)}"
    organization = Organization(
        id=org_id,
        name=body.organization_name,
        plan=body.plan,
        credits_balance=plan_config["credits"],
        monthly_quota=plan_config["monthly_quota"],
        rate_limit_per_minute=plan_config["rate_limit_per_minute"],
        rate_limit_per_day=plan_config["rate_limit_per_day"],
        billing_email=body.email,
    )
    db.add(organization)

    usr_prefix = PSS.get_str(db, "ID_PREFIX_USER")
    user_id = f"{usr_prefix}{secrets.token_hex(8)}"
    user = User(
        id=user_id,
        email=body.email,
        name=body.name,
        organization_id=org_id,
        # Public signups are plain members of their own org, NEVER platform
        # admins. `is_admin` (app/models/user.py) derives from role=="admin",
        # which is the gate for /api/v2/admin/* — see app/api/deps.py.
        role="member",
        password_hash=password_hash,
        email_verified=False,
        tos_accepted_at=utcnow().replace(tzinfo=None) if body.tos_accepted else None,
    )
    db.add(user)
    db.flush()

    # The signup creator owns the organization they just created. This is the
    # ONLY ownership signal (OrgOwnerUser dep). It does NOT grant platform-admin.
    organization.owner_user_id = user_id

    api_key_model, plaintext_key = APIKeyService.create_api_key(
        db=db,
        user_id=user_id,
        organization_id=org_id,
        name=PSS.get_str(db, "API_KEY_DEFAULT_NAME"),
        prefix=PSS.get_str(db, "API_KEY_DEFAULT_PREFIX"),
    )

    access_token = JWTService.create_access_token(
        user_id=user.id,
        org_id=org_id,
        is_admin=False,
        db=db,
    )
    refresh_token_str, jti = JWTService.create_refresh_token(user_id=user.id, db=db)

    rt_record = RefreshToken(
        user_id=user.id,
        jti=jti,
        expires_at=utcnow().replace(tzinfo=None)
        + timedelta(days=PSS.get_int(db, "JWT_REFRESH_TOKEN_EXPIRE_DAYS")),
    )
    db.add(rt_record)

    db.commit()
    db.refresh(organization)
    db.refresh(user)

    # Send verification email (best-effort)
    try:
        verification_token = JWTService.create_verification_token(user_id, db=db)
        verify_url = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
        logger.debug("Verification email sent to %s", body.email)

        from app.services.email_service import EmailService

        EmailService.send(
            to=body.email,
            subject="Verify your JAOT email",
            html=(
                f"<h2>Welcome to JAOT!</h2>"
                f"<p>Please verify your email by clicking the link below:</p>"
                f'<p><a href="{verify_url}">Verify Email</a></p>'
                f"<p>This link expires in 24 hours.</p>"
            ),
            db=db,
        )
    except Exception as e:
        logger.warning(f"Failed to send verification email: {e}")

    # Schedule onboarding emails (best-effort)
    try:
        from app.tasks.email_tasks import schedule_onboarding_sequence

        schedule_onboarding_sequence.delay(
            user_email=body.email,
            user_name=body.name,
            api_key_prefix=PSS.get_str(db, "API_KEY_DEFAULT_PREFIX"),
            locale=getattr(user, "locale", None),
        )
    except Exception:
        logger.debug("Failed to schedule onboarding emails", exc_info=True)

    # Fire-and-forget: log signup and org creation analytics events
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=user_id,
            org_id=org_id,
            event_type=evt.USER_SIGNUP,
            metadata={"method": "email"},
        )
        analytics.log_event(
            user_id=user_id,
            org_id=org_id,
            event_type=evt.ORG_CREATE,
            metadata={"org_name": organization.name},
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    response_data = {
        "user_id": user_id,
        "organization_id": org_id,
        "api_key": plaintext_key,
        "credits_balance": organization.credits_balance,
        "plan": body.plan,
        "message": (
            "Welcome to JAOT! Your account has been created. "
            "Please check your email to verify your address."
        ),
        "email_verified": False,
    }
    response = JSONResponse(content=response_data, status_code=201)
    _set_auth_cookies(response, access_token, refresh_token_str, db=db)

    return response


@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Verify user email with a token."""
    _rate_limit_or_raise(f"verify_email:{body.token[:16]}", limit_per_minute=5, limit_per_day=50)

    import jwt as pyjwt

    try:
        payload = JWTService.decode_token(body.token, db=db)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link has expired",
        ) from None
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        ) from None

    if payload.get("type") != "verify" or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found",
        )

    user.email_verified = True
    user.email_verified_at = utcnow().replace(tzinfo=None)
    db.commit()

    return {"success": True, "message": "Email verified successfully"}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Send a password reset email.

    Always returns 200 to prevent email enumeration.
    """
    # Rate limit by email: 3 per hour
    allowed, rate_info = check_rate_limit_hourly(
        f"reset:{body.email}",
        limit_per_hour=3,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    # Find user (only send if found and has password)
    user = db.query(User).filter(User.email == body.email).first()
    if user and user.password_hash:
        try:
            reset_token = JWTService.create_reset_token(user.id, db=db)
            reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
            logger.debug("Reset email sent to %s", body.email)

            from app.services.email_service import EmailService

            EmailService.send(
                to=body.email,
                subject="Reset your JAOT password",
                html=(
                    f"<h2>Password Reset</h2>"
                    f"<p>Click the link below to reset your password:</p>"
                    f'<p><a href="{reset_url}">Reset Password</a></p>'
                    f"<p>This link expires in 1 hour.</p>"
                    f"<p>If you didn't request this, please ignore this email.</p>"
                ),
                db=db,
            )
        except Exception as e:
            logger.warning(f"Failed to send reset email: {e}")

    # Always return success (anti-enumeration)
    return {
        "success": True,
        "message": "If this email is registered, you will receive a password reset link",
    }


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Reset password using a token."""
    _rate_limit_or_raise(f"reset_password:{body.token[:16]}", limit_per_minute=5, limit_per_day=50)

    import jwt as pyjwt

    try:
        payload = JWTService.decode_token(body.token, db=db)
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link has expired or is invalid",
        ) from None

    if payload.get("type") != "reset" or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link has expired or is invalid",
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link has expired or is invalid",
        )

    user.password_hash = PasswordService.hash_password(body.password)

    # Revoke all existing refresh tokens (force re-login everywhere)
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
    ).update({"revoked": True})

    db.commit()

    return {
        "success": True,
        "message": "Password has been reset. Please log in with your new password.",
    }


@router.post("/refresh")
async def refresh_token(request: Request, db: Session = Depends(get_db)) -> Response:
    """Refresh access token using refresh token cookie.

    Implements token rotation: old refresh token is revoked and a new one
    is issued.
    """
    import jwt as pyjwt

    refresh_cookie = request.cookies.get("jaot_refresh_token")
    if not refresh_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )

    try:
        payload = JWTService.decode_token(refresh_cookie, db=db)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        ) from None
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from None

    if payload.get("type") != "refresh" or not payload.get("jti"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    rt_record = db.query(RefreshToken).filter(RefreshToken.jti == payload["jti"]).first()
    if not rt_record or rt_record.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked",
        )

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization not found",
        )

    # Token rotation: revoke old, create new
    rt_record.revoked = True

    new_access_token = JWTService.create_access_token(
        user_id=user.id,
        org_id=org.id,
        is_admin=user.is_admin,
        db=db,
    )
    new_refresh_str, new_jti = JWTService.create_refresh_token(user_id=user.id, db=db)

    new_rt_record = RefreshToken(
        user_id=user.id,
        jti=new_jti,
        expires_at=utcnow().replace(tzinfo=None)
        + timedelta(days=PSS.get_int(db, "JWT_REFRESH_TOKEN_EXPIRE_DAYS")),
    )
    db.add(new_rt_record)
    db.commit()

    response = JSONResponse(content={"success": True, "message": "Token refreshed"})
    _set_auth_cookies(response, new_access_token, new_refresh_str, db=db)
    return response


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    """Log out by clearing cookies and revoking refresh token."""
    import jwt as pyjwt

    # Revoke refresh token if present
    refresh_cookie = request.cookies.get("jaot_refresh_token")
    if refresh_cookie:
        try:
            payload = JWTService.decode_token(refresh_cookie, db=db)
            jti = payload.get("jti")
            if jti:
                rt_record = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
                if rt_record:
                    rt_record.revoked = True
                    db.commit()
        except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
            pass  # Token already invalid, just clear cookies

    response = JSONResponse(content={"success": True, "message": "Logged out"})
    response.delete_cookie("jaot_access_token", path="/", secure=_cookie_secure, samesite="lax")
    response.delete_cookie(
        "jaot_refresh_token", path="/api/v2/auth", secure=_cookie_secure, samesite="lax"
    )
    return response


@router.get("/me", response_model=MeResponse)
def get_me(
    request: Request,
    db: Session = Depends(get_db),
) -> MeResponse:
    """Get current authenticated user info.

    Works with both JWT cookie and API key authentication.
    """
    user = get_current_user(request)
    org = get_current_organization(request)

    plan_config = PSS.get_plan_config_dynamic(db, org.plan)
    plan_limits = PlanLimitsResponse(
        max_variables=plan_config["max_variables"],
        max_solve_time_seconds=plan_config["max_solve_time_seconds"],
        max_daily_solves=plan_config["max_daily_solves"],
        allowed_features=plan_config["allowed_features"],
    )

    # D-7.1-06: is_org_owner is a READ-ONLY signal derived server-side.
    # org.owner_user_id may be NULL (legacy orgs created before the column
    # was added) — treat NULL as "no owner set" → False for safety.
    is_org_owner = bool(org.owner_user_id and org.owner_user_id == user.id)

    return MeResponse(
        user_id=user.id,
        user_name=user.name,
        user_email=user.email,
        organization_id=org.id,
        organization_name=org.name,
        plan=org.plan,
        credits_balance=org.credits_balance,
        is_admin=user.is_admin,
        is_org_owner=is_org_owner,
        can_build_plugins=user.can_build_plugins,
        skill_level=user.skill_level,
        guidance_state=user.guidance_state,
        email_verified=getattr(user, "email_verified", False),
        plan_limits=plan_limits,
    )


@router.post("/signup", response_model=SignupResponse)
async def signup(
    request: SignupRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
) -> SignupResponse:
    """Create a new user and organization (API key flow).

    This is a public endpoint - no authentication required.
    """
    client_ip = get_client_ip(raw_request)
    _rate_limit_or_raise(f"signup_ip:{client_ip}", limit_per_minute=3, limit_per_day=20)

    if not PSS.get_bool(db, "REGISTRATION_ENABLED"):
        raise HTTPException(
            status_code=503,
            detail=("Registration is currently disabled. Contact support@jaot.io for access."),
        )

    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    plan_config = PSS.get_plan_config_dynamic(db, request.plan)

    org_prefix = PSS.get_str(db, "ID_PREFIX_ORGANIZATION")
    org_id = f"{org_prefix}{secrets.token_hex(8)}"
    organization = Organization(
        id=org_id,
        name=request.organization_name,
        plan=request.plan,
        credits_balance=plan_config["credits"],
        monthly_quota=plan_config["monthly_quota"],
        rate_limit_per_minute=plan_config["rate_limit_per_minute"],
        rate_limit_per_day=plan_config["rate_limit_per_day"],
        billing_email=request.email,
    )
    db.add(organization)

    usr_prefix = PSS.get_str(db, "ID_PREFIX_USER")
    user_id = f"{usr_prefix}{secrets.token_hex(8)}"
    user = User(
        id=user_id,
        email=request.email,
        name=request.name,
        organization_id=org_id,
        # Public signups are plain members of their own org, NEVER platform
        # admins (see email-signup flow above and app/api/deps.py).
        role="member",
    )
    db.add(user)
    db.flush()

    # The signup creator owns the organization they just created (OrgOwnerUser).
    organization.owner_user_id = user_id

    api_key_model, plaintext_key = APIKeyService.create_api_key(
        db=db,
        user_id=user_id,
        organization_id=org_id,
        name=PSS.get_str(db, "API_KEY_DEFAULT_NAME"),
        prefix=PSS.get_str(db, "API_KEY_DEFAULT_PREFIX"),
    )

    db.commit()
    db.refresh(organization)
    db.refresh(user)

    # Schedule onboarding email sequence (non-blocking, best-effort)
    try:
        from app.tasks.email_tasks import schedule_onboarding_sequence

        schedule_onboarding_sequence.delay(
            user_email=request.email,
            user_name=request.name,
            api_key_prefix=PSS.get_str(db, "API_KEY_DEFAULT_PREFIX"),
            locale=getattr(user, "locale", None),
        )
    except Exception:
        logger.debug("Failed to schedule onboarding emails", exc_info=True)

    return SignupResponse(
        user_id=user_id,
        organization_id=org_id,
        api_key=plaintext_key,
        credits_balance=organization.credits_balance,
        plan=request.plan,
        message=(
            "Welcome to JAOT! Your organization has been created. "
            "Save your API key securely - it won't be shown again."
        ),
    )
