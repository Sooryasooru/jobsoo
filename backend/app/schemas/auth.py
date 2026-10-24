"""Authentication request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def _as_str(v: object) -> str:
    """Coerce UUID-like values (SQLAlchemy PKs) to their string form."""
    return str(v)


class RegisterRequest(BaseModel):
    """Registration payload. Password policy enforced here and again on the hash."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(default="", max_length=255)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    """Login payload. Identical error surfaces for unknown email and bad password."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    """Non-sensitive identity fields returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, v: object) -> str:
        return _as_str(v)


class SessionTokenResponse(BaseModel):
    """Bearer token issued by register/login."""

    token: str
    token_type: str = "bearer"  # noqa: S105 - static descriptor, not a secret
    user: UserResponse
