import ipaddress
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aiops_x_api.modules.cmdb.schemas import AssetType, Criticality, GxpClassification


class DiscoveryJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str = Field(min_length=2, max_length=160)
    networks: list[str] = Field(min_length=1, max_length=16)
    ports: list[int] = Field(
        default_factory=lambda: [22, 80, 443, 9100], min_length=1, max_length=16
    )
    timeout_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    max_hosts: int = Field(default=256, ge=1, le=256)
    enabled: bool = True
    schedule_enabled: bool = False
    schedule_interval_seconds: int = Field(default=300, ge=300, le=86400)

    @field_validator("networks")
    @classmethod
    def normalize_networks(cls, values: list[str]) -> list[str]:
        result = [str(ipaddress.ip_network(value, strict=False)) for value in values]
        if len(result) != len(set(result)):
            raise ValueError("duplicate network")
        return result

    @field_validator("ports")
    @classmethod
    def normalize_ports(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 65535 for value in values):
            raise ValueError("port must be between 1 and 65535")
        return sorted(set(values))


class DiscoveryJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    name: str
    discovery_type: str
    networks: list[str]
    ports: list[int]
    timeout_seconds: float
    max_hosts: int
    enabled: bool
    schedule_enabled: bool
    schedule_interval_seconds: int
    next_run_at: datetime | None
    run_count: int
    last_run_status: str
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class DiscoveryJobPage(BaseModel):
    items: list[DiscoveryJobResponse]
    page: int
    page_size: int
    total: int


class DiscoveryRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    discovery_job_id: UUID
    status: str
    observed_host_count: int
    candidate_count: int
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


class DiscoveryCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    discovery_job_id: UUID
    last_run_id: UUID
    ip_address: str
    hostname: str | None
    observed_ports: list[int]
    evidence: dict[str, object]
    status: str
    match_status: str
    matched_asset_id: UUID | None
    first_seen_at: datetime
    last_seen_at: datetime
    reviewed_at: datetime | None


class DiscoveryCandidatePage(BaseModel):
    items: list[DiscoveryCandidateResponse]
    page: int
    page_size: int
    total: int


class CandidateConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    existing_asset_id: UUID | None = None
    asset_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,63}$")
    asset_type: AssetType | None = None
    name: str | None = Field(default=None, min_length=2, max_length=160)
    environment: str = Field(default="unknown", min_length=2, max_length=32)
    criticality: Criticality = "medium"
    gxp_classification: GxpClassification = "unclassified"
    tags: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def require_link_or_asset_fields(self) -> "CandidateConfirm":
        creating = self.existing_asset_id is None
        if creating and (self.asset_id is None or self.asset_type is None or self.name is None):
            raise ValueError("asset_id, asset_type and name are required when creating an asset")
        if not creating and any(
            value is not None for value in (self.asset_id, self.asset_type, self.name)
        ):
            raise ValueError("asset creation fields cannot be combined with existing_asset_id")
        return self


class CandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["rejected"]
    reason: str = Field(min_length=3, max_length=500)


class CandidateConfirmationResponse(BaseModel):
    candidate_id: UUID
    asset_id: UUID
    status: str
