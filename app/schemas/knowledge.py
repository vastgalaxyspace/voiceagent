from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=6000)
    source_url: str = Field(default='', max_length=1000)

    @field_validator('title', 'content')
    @classmethod
    def meaningful_text(cls, value):
        value = value.strip()
        if not value or '\x00' in value:
            raise ValueError('Provide nonblank text without null characters')
        return value

    @field_validator('source_url')
    @classmethod
    def citation_url(cls, value):
        if not value:
            return ''
        parsed = str(TypeAdapter(HttpUrl).validate_python(value))
        if len(parsed) > 1000:
            raise ValueError('Source URL is too long')
        return parsed


class KnowledgeUpdate(KnowledgeCreate):
    expected_version: int = Field(ge=1)


class SharedKnowledgeCreate(KnowledgeCreate):
    published: bool = False


class SharedKnowledgeUpdate(SharedKnowledgeCreate):
    expected_version: int = Field(ge=1)


class KnowledgeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID | None
    title: str
    source_url: str
    published: bool
    version: int
    created_at: datetime
    updated_at: datetime


class KnowledgeResponse(KnowledgeSummary):
    content: str


class KnowledgePage(BaseModel):
    items: list[KnowledgeSummary]
    next_offset: int | None


class KnowledgeHit(BaseModel):
    id: UUID
    title: str
    source_url: str
    version: int
    excerpt: str
    offset: int


class KnowledgeSearch(BaseModel):
    items: list[KnowledgeHit]


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=3, ge=1, le=5)


class ReadKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    entry_id: str = Field(min_length=36, max_length=36)
    expected_version: int = Field(ge=1)
    offset: int = Field(default=0, ge=0, le=6000)
    max_chars: int = Field(default=800, ge=1, le=1000)

    @field_validator('entry_id')
    @classmethod
    def valid_uuid(cls, value):
        UUID(value)
        return value


class EmptyToolArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
