from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BootstrapStatus(BaseModel):
    required: bool


class BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_name: str = Field(min_length=2, max_length=120)
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
    email: str = Field(min_length=5, max_length=320)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("invalid email address")
        return normalized


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(min_length=3, max_length=80)
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("tenant_slug", "email")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return value.strip().lower()


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    email: str
    display_name: str
    is_active: bool
    is_bootstrap_admin: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=5, max_length=320)
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    role_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("invalid email address")
        return normalized


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    is_active: bool | None = None
    role_ids: list[UUID] | None = Field(default=None, max_length=20)


class PrincipalResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    display_name: str
    roles: list[str]
    permissions: list[str]
    is_bootstrap_admin: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: datetime
    csrf_token: str
    user: PrincipalResponse


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    description: str
    permissions: list[str]
    created_at: datetime


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    description: str = Field(default="", max_length=255)
    permissions: list[str] = Field(default_factory=list, max_length=100)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] | None = Field(default=None, max_length=100)
