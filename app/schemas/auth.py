from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class BaseCredentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(max_length=254)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class RegistrationCredentials(BaseCredentials):
    password: SecretStr = Field(
        min_length=4, max_length=8,
        description='New account password; must contain 4 to 8 characters.',
    )


class LoginCredentials(BaseCredentials):
    # Keep the historical upper bound so accounts created under the former
    # 12-128 character registration policy can continue to authenticate.
    password: SecretStr = Field(
        min_length=1, max_length=128,
        description='Account password. Legacy passwords longer than 8 characters remain valid.',
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    created_at: datetime
