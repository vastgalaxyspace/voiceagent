from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def meaningful_content(value):
    value = value.strip()
    if not value:
        raise ValueError('Memory content cannot be blank')
    if '\x00' in value:
        raise ValueError('Null characters are not supported')
    return value


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_]*$')
    content: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=50, ge=0, le=100)

    _content = field_validator('content')(meaningful_content)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=50, ge=0, le=100)
    expected_version: int = Field(ge=1)

    _content = field_validator('content')(meaningful_content)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    key: str
    content: str
    priority: int
    version: int
    created_at: datetime
    updated_at: datetime


class MemoryList(BaseModel):
    items: list[MemoryResponse]
    memory_enabled: bool
    limit: int
