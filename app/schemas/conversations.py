from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str | None = Field(default=None, max_length=500)
    use_tools: bool = False


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    prompt_version: str
    preferences_snapshot: dict
    configuration_snapshot: dict
    configuration_fingerprint: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    next_offset: int | None
