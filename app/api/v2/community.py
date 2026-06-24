"""Community integration endpoints: DiscourseConnect SSO and community status."""

import base64
import hashlib
import hmac
import logging
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession
from app.services.platform_settings_service import (
    PlatformSettingsService as PSS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/community", tags=["community"])


class CommunityStatusResponse(BaseModel):
    """Community feature availability response."""

    discourse_enabled: bool
    discourse_url: str | None = None


@router.get("/discourse-sso")
def discourse_sso(
    db: DBSession,
    sso: str = Query(..., description="Base64-encoded SSO payload from Discourse"),
    sig: str = Query(..., description="HMAC-SHA256 signature of the payload"),
    user: CurrentUser = None,  # type: ignore[assignment]
) -> RedirectResponse:
    """Handle DiscourseConnect SSO authentication.

    Discourse redirects users here with a signed payload. We validate
    the HMAC-SHA256 signature, extract the nonce, build a response
    payload with user data, sign it, and redirect back to Discourse.

    Returns 503 if DISCOURSE_SSO_SECRET is not configured.
    Returns 400 if the signature is invalid.
    """
    secret = PSS.get_str(db, "DISCOURSE_SSO_SECRET")
    discourse_url = PSS.get_str(db, "DISCOURSE_URL")

    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discourse SSO not configured",
        )

    # Validate HMAC-SHA256 signature (timing-safe comparison)
    expected_sig = hmac.new(secret.encode(), sso.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SSO signature",
        )

    # Decode payload and extract nonce
    decoded = base64.b64decode(sso).decode()
    params = parse_qs(decoded)
    nonce_list = params.get("nonce")
    if not nonce_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing nonce in SSO payload",
        )
    nonce = nonce_list[0]

    # Determine return URL
    return_sso_url = params.get(
        "return_sso_url",
        [discourse_url + "/session/sso_login"],
    )[0]

    response_payload = urlencode(
        {
            "nonce": nonce,
            "email": user.email,
            "external_id": user.id,
            "name": user.name,
            "username": user.email.split("@")[0],
            "suppress_welcome_message": "true",
        }
    )

    # Base64 encode and sign
    response_b64 = base64.b64encode(response_payload.encode()).decode()
    response_sig = hmac.new(secret.encode(), response_b64.encode(), hashlib.sha256).hexdigest()

    # Redirect back to Discourse
    redirect_url = f"{return_sso_url}?sso={response_b64}&sig={response_sig}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/status", response_model=CommunityStatusResponse)
def community_status(db: DBSession) -> CommunityStatusResponse:
    """Return which community features are enabled.

    This endpoint is public so the frontend can check availability
    before the user authenticates.
    """
    discourse_secret = PSS.get_str(db, "DISCOURSE_SSO_SECRET")
    discourse_url = PSS.get_str(db, "DISCOURSE_URL")

    discourse_enabled = bool(discourse_secret and discourse_url)

    return CommunityStatusResponse(
        discourse_enabled=discourse_enabled,
        discourse_url=discourse_url if discourse_enabled else None,
    )
