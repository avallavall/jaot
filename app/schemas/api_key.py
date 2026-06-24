"""API Key schemas."""

from pydantic import BaseModel, Field


class CreateKeyRequest(BaseModel):
    """Request to create a new API key."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    expires_days: int | None = Field(None, ge=1, le=365)


class APIKeyInfo(BaseModel):
    """API Key info (without the actual key)."""

    id: str
    name: str
    key_prefix: str
    description: str | None = None
    is_active: bool
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None


class CreateKeyResponse(BaseModel):
    """Response when creating a new API key."""

    api_key: str = Field(..., description="The newly created API key (shown only once)")
    id: str
    name: str
    description: str | None = None
    is_active: bool
    created_at: str


class KeyListResponse(BaseModel):
    """Paginated list of API keys."""

    items: list[APIKeyInfo]
    total: int
    page: int
    page_size: int
