from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Capability = Literal["discovery", "collector", "health_check", "action", "query", "notification"]


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,119}$")
    name: str = Field(min_length=2, max_length=160)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
    vendor: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    capabilities: list[Capability] = Field(min_length=1, max_length=20)
    supported_asset_types: list[str] = Field(max_length=100)
    configuration_schema: dict[str, Any]
    credential_types: list[str] = Field(max_length=20)
    required_permissions: list[str] = Field(max_length=100)
    risk_level: Literal["R0", "R1", "R2", "R3", "R4"]
    timeout: int = Field(ge=1, le=900)
    retry_policy: dict[str, Any]
    idempotent: bool
    health_check: dict[str, Any]
    entrypoint: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_.:-]{2,255}$")

    @model_validator(mode="after")
    def reject_unsafe_action_defaults(self) -> "PluginManifest":
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("plugin capabilities must be unique")
        if "action" in self.capabilities and self.risk_level == "R4":
            raise ValueError("R4 plugin actions are disabled")
        if "action" in self.capabilities and not self.required_permissions:
            raise ValueError("action plugins require explicit permissions")
        return self


class PluginContext(BaseModel):
    tenant_id: UUID
    project_id: UUID | None = None
    integration_id: UUID | None = None
    asset_id: UUID | None = None
    operation: str = Field(min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    credential_ref: str | None = None
    request_id: str
    trace_id: str


class PluginResult(BaseModel):
    success: bool
    status: str
    started_at: datetime
    finished_at: datetime
    evidence: list[dict[str, Any]] = Field(min_length=1)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    raw_output_ref: str | None = None
    sanitized_output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_traceability(self) -> "PluginResult":
        for item in self.evidence:
            if not item.get("source_ref") or not item.get("observed_at"):
                raise ValueError("plugin evidence requires source_ref and observed_at")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class DiscoveryPlugin(Protocol):
    async def discover(self, context: PluginContext) -> PluginResult: ...


class CollectorPlugin(Protocol):
    async def collect(self, context: PluginContext) -> PluginResult: ...


class HealthCheckPlugin(Protocol):
    async def check(self, context: PluginContext) -> PluginResult: ...


class ActionPlugin(Protocol):
    async def precheck(self, context: PluginContext) -> PluginResult: ...

    async def execute(self, context: PluginContext) -> PluginResult: ...

    async def postcheck(self, context: PluginContext) -> PluginResult: ...

    async def rollback(self, context: PluginContext) -> PluginResult: ...


class QueryPlugin(Protocol):
    async def query(self, context: PluginContext) -> PluginResult: ...


class NotificationPlugin(Protocol):
    async def send(self, context: PluginContext) -> PluginResult: ...
