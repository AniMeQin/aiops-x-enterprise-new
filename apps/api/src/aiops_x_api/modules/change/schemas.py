from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RiskLevel = Literal["R0", "R1", "R2", "R3", "R4"]
ChangeStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "scheduled",
    "in_progress",
    "validating",
    "completed",
    "failed",
    "rolled_back",
    "rejected",
    "cancelled",
]


class ChangeCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    change_type: Literal["standard", "normal", "emergency"] = "normal"
    risk_level: RiskLevel
    gxp_impact: bool = False
    affected_asset_ids: list[UUID] = Field(default_factory=list, max_length=500)
    incident_ids: list[UUID] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=500)
    implementation_plan: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    precheck_plan: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    validation_plan: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    success_criteria: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    rollback_plan: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    impact_analysis: dict[str, Any] = Field(default_factory=dict)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    configuration_backup_ref: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def enforce_risk_controls(self) -> "ChangeCreate":
        if self.risk_level == "R4":
            raise ValueError("R4 destructive changes are disabled")
        if (
            self.scheduled_start
            and self.scheduled_end
            and self.scheduled_end <= self.scheduled_start
        ):
            raise ValueError("scheduled_end must be after scheduled_start")
        if self.risk_level in {"R2", "R3"} or self.gxp_impact:
            if not self.precheck_plan or not self.validation_plan or not self.rollback_plan:
                raise ValueError(
                    "controlled changes require precheck, validation and rollback plans"
                )
        if self.risk_level == "R3" and not self.configuration_backup_ref:
            raise ValueError("R3 changes require a configuration backup reference")
        return self


class ChangeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    affected_asset_ids: list[UUID] | None = Field(default=None, max_length=500)
    incident_ids: list[UUID] | None = Field(default=None, max_length=100)
    evidence_ids: list[UUID] | None = Field(default=None, max_length=500)
    implementation_plan: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    precheck_plan: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    validation_plan: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    success_criteria: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    rollback_plan: list[dict[str, Any]] | None = Field(default=None, max_length=500)
    impact_analysis: dict[str, Any] | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    configuration_backup_ref: str | None = Field(default=None, max_length=512)


class ChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    change_number: str
    tenant_id: UUID
    project_id: UUID
    title: str
    description: str
    change_type: str
    risk_level: str
    status: str
    gxp_impact: bool
    affected_asset_ids: list[str]
    incident_ids: list[str]
    evidence_ids: list[str]
    implementation_plan: list[dict[str, Any]]
    precheck_plan: list[dict[str, Any]]
    validation_plan: list[dict[str, Any]]
    success_criteria: list[dict[str, Any]]
    rollback_plan: list[dict[str, Any]]
    impact_analysis: dict[str, Any]
    approval_policy_snapshot: dict[str, Any]
    required_approvals: int
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    configuration_backup_ref: str | None
    automation_job_id: UUID | None
    requested_by: UUID
    submitted_at: datetime | None
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=1000)


class ApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    change_id: UUID
    decision: str
    approver_id: UUID
    comment: str
    decided_at: datetime


class ChangeStatusUpdate(BaseModel):
    status: Literal[
        "scheduled", "in_progress", "validating", "completed", "failed", "rolled_back", "cancelled"
    ]
    failure_reason: str | None = Field(default=None, max_length=500)
    automation_job_id: UUID | None = None

    @model_validator(mode="after")
    def require_failure_context(self) -> "ChangeStatusUpdate":
        if self.status in {"failed", "rolled_back"} and not self.failure_reason:
            raise ValueError("failed and rolled_back changes require failure_reason")
        return self


class ChangeTimelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    change_id: UUID
    occurred_at: datetime
    status: str
    title: str
    details: dict[str, Any]
    created_by: UUID


class ChangeDetail(ChangeResponse):
    approvals: list[ApprovalDecisionResponse]
    timeline: list[ChangeTimelineResponse]


class ChangePage(BaseModel):
    items: list[ChangeResponse]
    page: int
    page_size: int
    total: int
