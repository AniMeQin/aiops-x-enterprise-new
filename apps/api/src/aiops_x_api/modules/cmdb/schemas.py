import ipaddress
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

AssetType = Literal[
    "linux",
    "windows",
    "vmware",
    "physical_server",
    "network_device",
    "firewall",
    "load_balancer",
    "docker",
    "kubernetes_cluster",
    "pod",
    "database",
    "middleware",
    "application",
    "cloud_resource",
    "security_device",
    "custom",
]
Criticality = Literal["low", "medium", "high", "critical"]
GxpClassification = Literal["gxp", "non_gxp", "unclassified"]
LifecycleStatus = Literal["active", "maintenance", "retired"]
RelationType = Literal[
    "DEPENDS_ON",
    "RUNS_ON",
    "CONNECTS_TO",
    "MEMBER_OF",
    "MANAGED_BY",
    "STORES_DATA_IN",
    "EXPOSES",
    "BACKED_UP_TO",
    "MONITORED_BY",
]
RelationConfidence = Literal["unknown", "low", "medium", "high"]


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}$")
    project_id: UUID
    asset_type: AssetType
    name: str = Field(min_length=2, max_length=160)
    hostname: str | None = Field(default=None, max_length=255)
    ip_addresses: list[str] = Field(default_factory=list, max_length=32)
    operating_system: str | None = Field(default=None, max_length=120)
    operating_system_version: str | None = Field(default=None, max_length=120)
    business_service: str | None = Field(default=None, max_length=160)
    environment: str = Field(default="unknown", min_length=2, max_length=32)
    owner: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    criticality: Criticality = "medium"
    gxp_classification: GxpClassification = "unclassified"
    lifecycle_status: LifecycleStatus = "active"
    credential_ref: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=64)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ip_addresses")
    @classmethod
    def validate_ip_addresses(cls, values: list[str]) -> list[str]:
        normalized = [str(ipaddress.ip_address(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate IP address")
        return normalized

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("vault://", "secret://")):
            raise ValueError("credential_ref must use vault:// or secret://")
        return value


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    hostname: str | None = Field(default=None, max_length=255)
    ip_addresses: list[str] | None = Field(default=None, max_length=32)
    operating_system: str | None = Field(default=None, max_length=120)
    operating_system_version: str | None = Field(default=None, max_length=120)
    business_service: str | None = Field(default=None, max_length=160)
    environment: str | None = Field(default=None, min_length=2, max_length=32)
    owner: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    criticality: Criticality | None = None
    gxp_classification: GxpClassification | None = None
    lifecycle_status: LifecycleStatus | None = None
    credential_ref: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = Field(default=None, max_length=64)
    custom_attributes: dict[str, Any] | None = None

    @field_validator("ip_addresses")
    @classmethod
    def validate_ip_addresses(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [str(ipaddress.ip_address(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate IP address")
        return normalized

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("vault://", "secret://")):
            raise ValueError("credential_ref must use vault:// or secret://")
        return value


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: str
    tenant_id: UUID
    project_id: UUID
    asset_type: str
    name: str
    hostname: str | None
    ip_addresses: list[str]
    operating_system: str | None
    operating_system_version: str | None
    business_service: str | None
    environment: str
    owner: str | None
    department: str | None
    location: str | None
    criticality: str
    gxp_classification: str
    lifecycle_status: str
    agent_status: str
    monitoring_status: str
    credential_configured: bool
    tags: list[str]
    custom_attributes: dict[str, Any]
    discovery_source: str | None
    discovery_status: str
    last_connected_at: datetime | None
    last_monitored_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssetPage(BaseModel):
    items: list[AssetResponse]
    page: int
    page_size: int
    total: int


class AssetRelationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_asset_id: UUID
    relation_type: RelationType
    source: str = Field(min_length=2, max_length=120)
    confidence: RelationConfidence = "unknown"
    effective_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    manually_confirmed: bool = False

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime | None, info: ValidationInfo) -> datetime | None:
        effective_at = info.data.get("effective_at")
        if value is not None and effective_at is not None and value <= effective_at:
            raise ValueError("expires_at must be later than effective_at")
        return value


class AssetRelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    source_asset_id: UUID
    target_asset_id: UUID
    relation_type: str
    source: str
    confidence: str
    effective_at: datetime
    expires_at: datetime | None
    manually_confirmed: bool


class AssetRelationPage(BaseModel):
    items: list[AssetRelationResponse]
    page: int
    page_size: int
    total: int


ComponentType = Literal[
    "interface",
    "service",
    "container",
    "kubernetes_workload",
    "database_instance",
]


class AssetComponentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_component_id: UUID | None = None
    component_type: ComponentType
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    status: str = Field(default="unknown", min_length=2, max_length=32)
    source: str = Field(min_length=2, max_length=120)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssetComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    parent_component_id: UUID | None
    component_type: str
    external_id: str
    name: str
    status: str
    source: str
    attributes: dict[str, Any]
    observed_at: datetime
    created_at: datetime
    updated_at: datetime


class AssetComponentPage(BaseModel):
    items: list[AssetComponentResponse]
    page: int
    page_size: int
    total: int
