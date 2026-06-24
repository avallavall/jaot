"""GDPR endpoints: data export and account deletion."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_organization, get_current_user
from app.config import settings
from app.models import Organization, User
from app.schemas.gdpr import AccountDeleteRequest
from app.services.auth import PasswordService
from app.services.gdpr_service import delete_user_account, export_user_data
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

# Cookie security: derive from DEBUG setting (secure=True in production)
_cookie_secure = not settings.DEBUG

router = APIRouter(prefix="/user")


@router.get("/data-export")
def data_export(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Export all user data as a downloadable JSON file (GDPR data portability)."""
    user: User = get_current_user(request)
    org: Organization = get_current_organization(request)

    data = export_user_data(db, user, org)
    content = json.dumps(data, indent=2, default=str)

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="jaot-data-export-{user.id}.json"',
        },
    )


@router.delete("/account")
def delete_account(
    body: AccountDeleteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Delete user account and all associated data (GDPR right to erasure).

    Requires password confirmation and the word "DELETE" as confirmation.
    """
    user: User = get_current_user(request)

    # Verify password
    if not user.password_hash or not PasswordService.verify_password(
        body.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    delete_user_account(db, user)
    db.commit()

    # Build response -- clear auth cookies
    response = JSONResponse(
        content={"success": True, "message": "Account deleted successfully"},
    )
    response.delete_cookie("jaot_access_token", path="/", secure=_cookie_secure, samesite="lax")
    response.delete_cookie(
        "jaot_refresh_token", path="/api/v2/auth", secure=_cookie_secure, samesite="lax"
    )
    return response
