from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegistrationTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    asset_id: UUID
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)


class RegistrationTokenResponse(BaseModel):
    id: UUID
    token: str
    token_prefix: str
    project_id: UUID
    asset_id: UUID
    expires_at: datetime


class AgentEnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_token: str = Field(min_length=32, max_length=256)
    name: str = Field(min_length=2, max_length=160)
    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=2, max_length=64)
    architecture: str = Field(min_length=2, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    csr_pem: str = Field(min_length=100, max_length=16_384)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class AgentEnrollmentResponse(BaseModel):
    agent_id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    certificate_pem: str
    ca_certificate_pem: str
    task_signing_certificate_pem: str
    certificate_not_after: datetime


class AgentCertificateRenewalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csr_pem: str = Field(min_length=100, max_length=16_384)


class AgentCertificateRenewalResponse(BaseModel):
    agent_id: UUID
    certificate_pem: str
    ca_certificate_pem: str
    task_signing_certificate_pem: str
    certificate_not_after: datetime


class AgentHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=2, max_length=64)
    architecture: str = Field(min_length=2, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    health_status: Literal["healthy", "degraded"]
    capabilities: dict[str, Any]

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: dict[str, Any]) -> dict[str, Any]:
        actions = value.get("actions", [])
        if not isinstance(actions, list) or any(
            action != "system.disk_usage" for action in actions
        ):
            raise ValueError("unregistered Agent action")
        return value


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    name: str
    hostname: str
    platform: str
    architecture: str
    version: str
    status: str
    health_status: str
    capabilities: dict[str, Any]
    certificate_not_after: datetime
    last_heartbeat_at: datetime | None
    disabled_at: datetime | None
    disabled_by: UUID | None
    disable_reason: str | None
    registered_at: datetime


class AgentDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class AgentPage(BaseModel):
    items: list[AgentResponse]
    page: int
    page_size: int
    total: int


class AgentTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: Literal["system.disk_usage"]
    parameters: dict[str, Any] = Field(default_factory=lambda: {"paths": ["/"]})
    expires_in_seconds: int = Field(default=300, ge=30, le=900)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) - {"paths"}:
            raise ValueError("system.disk_usage only accepts paths")
        paths = value.get("paths", ["/"])
        if not isinstance(paths, list) or not 1 <= len(paths) <= 8:
            raise ValueError("paths must contain between 1 and 8 entries")
        if any(
            not isinstance(path, str) or not path.startswith("/") or len(path) > 255
            for path in paths
        ):
            raise ValueError("each path must be an absolute path")
        return {"paths": paths}


class AgentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    agent_id: UUID
    automation_job_id: UUID | None
    action_id: str
    parameters: dict[str, Any]
    risk_level: str
    status: str
    expires_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    sanitized_output: dict[str, Any]
    error_code: str | None
    error_message: str | None
    raw_output_ref: str | None
    created_at: datetime


class AgentTaskPage(BaseModel):
    items: list[AgentTaskResponse]
    page: int
    page_size: int
    total: int


class AgentTaskEnvelope(BaseModel):
    task_id: UUID
    signing_payload: str
    signature: str
    signature_algorithm: Literal["x509-sha256"] = "x509-sha256"


class AgentTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed"]
    duration_ms: int = Field(ge=0, le=900_000)
    sanitized_output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=500)

    @field_validator("sanitized_output")
    @classmethod
    def limit_output(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json

        if len(json.dumps(value, separators=(",", ":")).encode()) > 65_536:
            raise ValueError("sanitized output exceeds 64 KiB")
        return value
