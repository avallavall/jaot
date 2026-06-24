"""Attachment request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


class AttachmentResponse(BaseModel):
    """Response schema for a conversation attachment."""

    id: str
    filename: str
    mime_type: str
    char_count: int
    preview: str
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_tokens(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return self.char_count // 4

    model_config = ConfigDict(from_attributes=True)
