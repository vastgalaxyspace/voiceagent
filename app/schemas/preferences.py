from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal['English', 'Hindi', 'English and Hindi']
ResponseDetail = Literal['brief', 'detailed']
ConversationMode = Literal['general', 'english_practice', 'interview_practice']


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Language | None = None
    response_detail: ResponseDetail | None = None
    goal: str | None = Field(default=None, max_length=500)
    display_name: str | None = Field(default=None, max_length=80)
    pronouns: str | None = Field(default=None, max_length=80)
    custom_instructions: str | None = Field(default=None, max_length=1000)
    conversation_mode: ConversationMode | None = None
    memory_enabled: bool | None = None

    @field_validator('goal', 'display_name', 'custom_instructions', 'pronouns')
    @classmethod
    def supported_text(cls, value):
        if value is not None and '\x00' in value:
            raise ValueError('Null characters are not supported')
        return value


class PreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language: Language
    response_detail: ResponseDetail
    goal: str
    display_name: str
    pronouns: str
    custom_instructions: str
    conversation_mode: ConversationMode
    memory_enabled: bool
    updated_at: datetime
