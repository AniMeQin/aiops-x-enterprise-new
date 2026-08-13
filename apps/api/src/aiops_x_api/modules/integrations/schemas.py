from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

IntegrationType = Literal[
    "prometheus",
    "alertmanager",
    "webhook",
    "grafana",
    "loki",
    "tempo",
    "network",
    "windows",
    "docker",
    "kubernetes",
    "database",
    "security",
    "notification",
]


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,118}[a-z0-9]$")
    name: str = Field(min_length=2, max_length=160)
    integration_type: IntegrationType
    endpoint: str = Field(min_length=8, max_length=512)
    credential_ref: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("integration endpoint must use HTTP or HTTPS")
        return normalized

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("vault://", "secret://")):
            raise ValueError("credential_ref must use vault:// or secret://")
        return value


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    endpoint: str | None = Field(default=None, min_length=8, max_length=512)
    credential_ref: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    capabilities: list[str] | None = Field(default=None, max_length=32)
    configuration: dict[str, Any] | None = None

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("integration endpoint must use HTTP or HTTPS")
        return normalized

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("vault://", "secret://")):
            raise ValueError("credential_ref must use vault:// or secret://")
        return value


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID | None
    slug: str
    name: str
    integration_type: str
    endpoint: str
    credential_configured: bool
    enabled: bool
    health_status: str
    last_checked_at: datetime | None
    last_sync_at: datetime | None
    sync_error: str | None
    config_version: int
    capabilities: list[str]
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IntegrationPage(BaseModel):
    items: list[IntegrationResponse]
    page: int
    page_size: int
    total: int


class IntegrationProbeResult(BaseModel):
    id: UUID
    health_status: Literal["healthy", "unhealthy", "disabled"]
    checked_at: datetime
    message: str
