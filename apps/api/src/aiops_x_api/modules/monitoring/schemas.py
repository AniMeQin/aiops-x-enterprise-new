from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MonitorTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    asset_id: UUID
    name: str = Field(min_length=2, max_length=160)
    target_type: Literal["node_exporter"] = "node_exporter"
    prometheus_job: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    prometheus_instance: str = Field(min_length=1, max_length=255)
    identity_label: Literal["aiops_asset_id"] = "aiops_asset_id"
    purpose: Literal["node_metrics"] = "node_metrics"


class MonitorBindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    monitor_target_id: UUID
    purpose: str
    identity_label: str
    identity_value: str
    enabled: bool
    verification_status: str
    last_verified_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class MonitorTargetResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    name: str
    target_type: str
    prometheus_job: str
    prometheus_instance: str
    tenant_slug: str
    project_slug: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    binding: MonitorBindingResponse


class MonitorTargetPage(BaseModel):
    items: list[MonitorTargetResponse]
    page: int
    page_size: int
    total: int


class MonitorTargetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    prometheus_job: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    prometheus_instance: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_changes(self) -> "MonitorTargetUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class MonitorTargetVerificationResponse(BaseModel):
    target_id: UUID
    binding_id: UUID
    status: Literal["verified", "failed"]
    verified_at: datetime
    error_code: str | None
    sample_timestamp: datetime | None
    target_up: bool | None


class MetricSampleResponse(BaseModel):
    metric: dict[str, str]
    timestamp: datetime
    value: float


class NodeMetricsResponse(BaseModel):
    asset_id: UUID
    target_id: UUID
    binding_id: UUID
    source: Literal["prometheus"] = "prometheus"
    collected_at: datetime
    sample_timestamp: datetime
    age_seconds: float
    freshness_status: Literal["fresh"] = "fresh"
    target_up: bool
    cpu_usage_percent: float | None
    memory_usage_percent: float | None
    root_filesystem_usage_percent: float | None
    raw_samples: dict[str, list[MetricSampleResponse]]
