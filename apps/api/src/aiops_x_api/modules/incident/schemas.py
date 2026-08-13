from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

IncidentSeverity = Literal["info", "warning", "critical", "emergency"]
IncidentStatus = Literal[
    "open", "acknowledged", "investigating", "mitigated", "resolved", "closed", "cancelled"
]


class IncidentCreate(BaseModel):
    project_id: UUID
    source_event_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    severity: IncidentSeverity
    owner_id: UUID | None = None
    participant_ids: list[UUID] = Field(default_factory=list, max_length=100)
    impact_scope: dict[str, Any] = Field(default_factory=dict)
    asset_ids: list[UUID] = Field(default_factory=list, max_length=500)
    alert_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    change_ids: list[UUID] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=500)
    sla_policy: dict[str, Any] = Field(default_factory=dict)
    response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None


class IncidentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    owner_id: UUID | None = None
    participant_ids: list[UUID] | None = Field(default=None, max_length=100)
    impact_scope: dict[str, Any] | None = None
    asset_ids: list[UUID] | None = Field(default=None, max_length=500)
    alert_ids: list[UUID] | None = Field(default=None, max_length=1000)
    change_ids: list[UUID] | None = Field(default=None, max_length=100)
    evidence_ids: list[UUID] | None = Field(default=None, max_length=500)
    root_cause_candidates: list[dict[str, Any]] | None = Field(default=None, max_length=100)
    resolution_steps: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    approval_refs: list[str] | None = Field(default=None, max_length=100)
    restored_at: datetime | None = None


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_number: str
    tenant_id: UUID
    project_id: UUID
    source_event_id: UUID | None
    title: str
    description: str
    severity: str
    status: str
    owner_id: UUID | None
    participant_ids: list[str]
    impact_scope: dict[str, Any]
    asset_ids: list[str]
    alert_ids: list[str]
    change_ids: list[str]
    evidence_ids: list[str]
    root_cause_candidates: list[dict[str, Any]]
    resolution_steps: list[dict[str, Any]]
    approval_refs: list[str]
    sla_policy: dict[str, Any]
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    restored_at: datetime | None
    closed_at: datetime | None
    response_due_at: datetime | None
    resolution_due_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class IncidentPage(BaseModel):
    items: list[IncidentResponse]
    page: int
    page_size: int
    total: int


class TimelineEntryCreate(BaseModel):
    occurred_at: datetime
    entry_type: Literal[
        "observation", "action", "decision", "status_change", "communication", "evidence"
    ]
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    occurred_at: datetime
    entry_type: str
    title: str
    description: str
    evidence_ids: list[str]
    metadata_json: dict[str, Any]
    created_by: UUID
    created_at: datetime


class PostmortemUpsert(BaseModel):
    status: Literal["draft", "in_review", "approved", "published"] = "draft"
    summary: str = Field(default="", max_length=20000)
    customer_impact: str = Field(default="", max_length=20000)
    root_cause: str = Field(default="", max_length=20000)
    trigger: str = Field(default="", max_length=10000)
    detection: str = Field(default="", max_length=10000)
    response: str = Field(default="", max_length=20000)
    resolution: str = Field(default="", max_length=20000)
    lessons_learned: str = Field(default="", max_length=20000)
    action_items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=500)
    report_object_ref: str | None = Field(default=None, max_length=512)
    generated_by: Literal["human", "ai_assisted"] = "human"

    @model_validator(mode="after")
    def approved_requires_content(self) -> "PostmortemUpsert":
        if self.status in {"approved", "published"} and not (
            self.summary.strip() and self.root_cause.strip() and self.action_items
        ):
            raise ValueError("approved postmortems require summary, root cause and action items")
        if self.generated_by == "ai_assisted" and not self.evidence_ids:
            raise ValueError("AI-assisted postmortems require evidence references")
        return self


class PostmortemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    status: str
    summary: str
    customer_impact: str
    root_cause: str
    trigger: str
    detection: str
    response: str
    resolution: str
    lessons_learned: str
    action_items: list[dict[str, Any]]
    evidence_ids: list[str]
    report_object_ref: str | None
    generated_by: str
    approved_by: UUID | None
    approved_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentResponse):
    timeline: list[TimelineEntryResponse]
    postmortem: PostmortemResponse | None
