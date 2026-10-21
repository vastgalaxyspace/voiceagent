"""Validated client messages for the live WebSocket protocol."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StartMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['start']
    language: Literal['English', 'Hindi', 'English and Hindi'] = 'English and Hindi'
    goal: str = Field(default='', max_length=500)


class AuthenticatedStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['start']
    conversation_id: UUID
    access_token: SecretStr | None = Field(default=None, max_length=128)
