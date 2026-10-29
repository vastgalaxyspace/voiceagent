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
    title: str = ''
    preview: str = ''
    message_count: int = 0
    last_message_at: datetime | None = None
    has_user_message: bool = False
    transcript_status: str = 'unavailable'
    continued_from_id: UUID | None = None
    summary_version: int = 0


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    next_offset: int | None


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    preview: str
    created_at: datetime
    last_message_at: datetime | None
    message_count: int
    transcript_status: str
    status: str


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    next_offset: int | None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    sequence: int
    role: str
    text: str
    state: str
    revision: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class MessagePage(BaseModel):
    conversation_id: UUID
    transcript_status: str
    items: list[MessageResponse]
    next_sequence: int | None
