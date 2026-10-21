from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(max_length=254)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    created_at: datetime
