from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SloCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    service_ref: str = Field(min_length=1, max_length=255)
    sli_type: Literal["availability", "latency", "quality", "custom"]
    prometheus_query: str = Field(min_length=1, max_length=5000)
    target: float = Field(gt=0, lt=1)
    window_days: int = Field(default=30, ge=1, le=90)
    warning_burn_rate: float = Field(default=1.0, gt=0, le=100)
    critical_burn_rate: float = Field(default=2.0, gt=0, le=100)
    labels: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_burn_rates(self) -> "SloCreate":
        if self.critical_burn_rate <= self.warning_burn_rate:
            raise ValueError("critical burn rate must exceed warning burn rate")
        return self


class SloResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    name: str
    description: str
    service_ref: str
    sli_type: str
    prometheus_query: str
    target: float
    window_days: int
    warning_burn_rate: float
    critical_burn_rate: float
    enabled: bool
    labels: dict[str, Any]
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SloPage(BaseModel):
    items: list[SloResponse]
    page: int
    page_size: int
    total: int


class SloEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slo_id: UUID
    status: str
    indicator_value: float
    target: float
    error_budget_remaining: float
    burn_rate: float
    query_time: datetime
    source_ref: str
    raw_sample: dict[str, Any]
    evaluated_at: datetime


class CapacityAnalysisCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=160)
    resource_type: Literal["cpu", "memory", "disk", "network", "requests", "database", "custom"]
    service_ref: str = Field(min_length=1, max_length=255)
    prometheus_query: str = Field(min_length=1, max_length=5000)
    lookback_hours: int = Field(default=168, ge=2, le=2160)
    forecast_hours: int = Field(default=168, ge=1, le=2160)
    warning_threshold: float
    critical_threshold: float

    @model_validator(mode="after")
    def validate_thresholds(self) -> "CapacityAnalysisCreate":
        if self.critical_threshold <= self.warning_threshold:
            raise ValueError("critical threshold must exceed warning threshold")
        return self


class CapacityAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_id: str
    tenant_id: UUID
    project_id: UUID
    name: str
    resource_type: str
    service_ref: str
    prometheus_query: str
    lookback_hours: int
    forecast_hours: int
    warning_threshold: float
    critical_threshold: float
    status: str
    result: dict[str, Any]
    source_ref: str
    created_by: UUID
    created_at: datetime


class CapacityAnalysisPage(BaseModel):
    items: list[CapacityAnalysisResponse]
    page: int
    page_size: int
    total: int
