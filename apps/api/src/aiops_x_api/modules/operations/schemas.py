from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = ""
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = "4"
    receiver: str = ""
    status: Literal["firing", "resolved"]
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=100)


class WebhookResult(BaseModel):
    received: int
    created: int
    deduplicated: int
    resolved: int
    suppressed: int
    event_ids: list[str]


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: str
    source: str
    external_id: str
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    fingerprint: str
    correlation_key: str
    title: str
    description: str
    severity: str
    status: str
    labels: dict[str, Any]
    annotations: dict[str, Any]
    starts_at: datetime
    ends_at: datetime | None
    received_at: datetime
    last_received_at: datetime
    evidence_refs: list[dict[str, Any]]
    raw_data_ref: str | None
    duplicate_count: int


class AlertPage(BaseModel):
    items: list[AlertResponse]
    page: int
    page_size: int
    total: int


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: str
    tenant_id: UUID
    project_id: UUID
    primary_asset_id: UUID
    correlation_key: str
    title: str
    description: str
    severity: str
    status: str
    affected_asset_ids: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    ai_summary_status: str
    ai_summary: str | None
    created_at: datetime
    updated_at: datetime


class EventPage(BaseModel):
    items: list[EventResponse]
    page: int
    page_size: int
    total: int


class EventAsset(BaseModel):
    id: UUID
    asset_id: str
    name: str
    hostname: str | None
    ip_addresses: list[str]
    monitoring_status: str


class TimelineEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    occurred_at: datetime
    category: str
    title: str
    description: str
    source_type: str
    source_id: str | None
    evidence_refs: list[dict[str, Any]]
    metadata_json: dict[str, Any]


class EventAutomationJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    runbook_id: UUID
    runbook_version: int
    action_id: str
    risk_level: str
    status: str
    approval_status: str
    inputs: dict[str, Any]
    sanitized_output: dict[str, Any]
    duration_ms: int | None
    created_at: datetime


class EventDetail(EventResponse):
    asset: EventAsset
    alerts: list[AlertResponse]
    timeline: list[TimelineEntryResponse]
    automation_jobs: list[EventAutomationJob]


class MaintenanceWindowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    asset_id: UUID | None = None
    name: str = Field(min_length=2, max_length=160)
    starts_at: datetime
    ends_at: datetime


class MaintenanceWindowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool | None = None


class MaintenanceWindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID | None
    name: str
    starts_at: datetime
    ends_at: datetime
    enabled: bool
    created_by: UUID
    created_at: datetime


class MaintenanceWindowPage(BaseModel):
    items: list[MaintenanceWindowResponse]
    page: int
    page_size: int
    total: int
