from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from aiops_x_plugin_sdk import PluginManifest, PluginResult
from pydantic import BaseModel, ConfigDict, Field


class PluginRegister(BaseModel):
    manifest: PluginManifest
    enabled: bool = True


class PluginDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    plugin_id: str
    name: str
    version: str
    vendor: str
    description: str
    capabilities: list[str]
    supported_asset_types: list[str]
    configuration_schema: dict[str, Any]
    credential_types: list[str]
    required_permissions: list[str]
    risk_level: str
    timeout_seconds: int
    retry_policy: dict[str, Any]
    idempotent: bool
    health_check: dict[str, Any]
    entrypoint: str
    enabled: bool
    manifest_hash: str
    created_by: UUID
    created_at: datetime


class PluginInvocationRequest(BaseModel):
    integration_id: UUID
    project_id: UUID | None = None
    asset_id: UUID | None = None
    capability: Literal["discovery", "collector", "health_check", "query", "notification"]
    operation: str = Field(min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PluginInvocationResponse(BaseModel):
    invocation_id: UUID
    plugin_id: str
    capability: str
    operation: str
    result: PluginResult


class BuiltinPluginResult(BaseModel):
    registered: list[PluginDefinitionResponse]
    unchanged: list[str]
