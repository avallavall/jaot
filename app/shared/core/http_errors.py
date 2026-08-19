"""HTTP errors that a localized interface can render.

``HTTPException`` carries one string. That string is English, and for the browser
it is the wrong thing to show: the four authentication screens were printing raw
API text under otherwise fully translated pages.

``CodedHTTPException`` adds a stable ``code`` (plus optional ``params``) to the
response body **without changing ``detail``** — API and MCP clients keep reading
exactly what they read before, and the interface renders the code in the reader's
language. Same shape as the insight and notification codes.

    raise CodedHTTPException(
        status_code=423,
        detail=f"Account temporarily locked. Try again in {minutes} minutes.",
        code="auth.account_locked",
        params={"minutes": minutes},
    )

    → 423 {"detail": "Account temporarily locked...", "code": "auth.account_locked",
           "params": {"minutes": 3}}
"""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class CodedHTTPException(HTTPException):
    """An HTTPException that also names itself for a translating client."""

    def __init__(
        self,
        status_code: int,
        # Usually the English sentence. A 429 carries the rate limiter's own
        # object instead — `{"error", "message", "limit", "remaining",
        # "reset_at", "retry_after"}` — which clients already read, so it is
        # passed through untouched here rather than flattened to a string.
        detail: Any,
        code: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.params = params or {}


async def coded_http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Serialize a CodedHTTPException, additively: ``detail`` is untouched."""
    assert isinstance(exc, CodedHTTPException)  # nosec B101 — registered for this type only
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "params": exc.params},
        headers=exc.headers,
    )
