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
    prometheus_job: Literal["node"] = "node"
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
    prometheus_job: Literal["node"] | None = None
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


class MetricPointResponse(BaseModel):
    timestamp: datetime
    value: float


class MetricSeriesResponse(BaseModel):
    metric: dict[str, str]
    points: list[MetricPointResponse]


class NodeMetricHistoryResponse(BaseModel):
    asset_id: UUID
    target_id: UUID
    metric_name: str
    source: Literal["prometheus"] = "prometheus"
    start: datetime
    end: datetime
    step_seconds: int
    series: list[MetricSeriesResponse]


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


class AlertRuleVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_key: Literal["host_down", "cpu", "memory", "filesystem"]
    operator: Literal[">", "<", "=="] = ">"
    threshold: float = Field(ge=0, le=100)
    duration_seconds: int = Field(default=300, ge=0, le=86400)
    severity: Literal["info", "warning", "critical"] = "warning"
    summary: str = Field(min_length=3, max_length=255)
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_metric_condition(self) -> "AlertRuleVersionInput":
        if self.metric_key == "host_down" and (self.operator != "==" or self.threshold != 0):
            raise ValueError("host_down requires operator == and threshold 0")
        return self


class AlertRuleCreate(AlertRuleVersionInput):
    project_id: UUID
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{2,119}$")
    name: str = Field(min_length=2, max_length=160)


class AlertRuleVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_rule_id: UUID
    version: int
    metric_key: str
    operator: str
    threshold: float
    duration_seconds: int
    severity: str
    expression: str
    labels: dict[str, str]
    annotations: dict[str, str]
    status: str
    published_at: datetime | None
    created_at: datetime


class AlertRuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    slug: str
    name: str
    enabled: bool
    current_version: int
    published_version: int | None
    created_at: datetime
    updated_at: datetime
    version: AlertRuleVersionResponse


class AlertRulePage(BaseModel):
    items: list[AlertRuleResponse]
    page: int
    page_size: int
    total: int
