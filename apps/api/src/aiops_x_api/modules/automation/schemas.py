from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RunbookVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    runbook_id: UUID
    version: int
    action_id: str
    asset_types: list[str]
    input_schema: dict[str, Any]
    risk_level: str
    required_permissions: list[str]
    timeout_seconds: int
    retry_policy: dict[str, Any]
    idempotent: bool
    pre_checks: list[dict[str, Any]]
    execution_steps: list[dict[str, Any]]
    post_checks: list[dict[str, Any]]
    success_conditions: list[str]
    failure_conditions: list[str]
    rollback_steps: list[dict[str, Any]]
    approval_policy: dict[str, Any]
    maintenance_window_required: bool
    output_redaction_rules: list[str]
    checksum: str
    created_at: datetime


class RunbookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    slug: str
    name: str
    description: str
    status: str
    current_version: int
    created_at: datetime
    updated_at: datetime
    versions: list[RunbookVersionResponse] = Field(default_factory=list)


class RunbookPage(BaseModel):
    items: list[RunbookResponse]
    page: int
    page_size: int
    total: int


class BuiltinRunbookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID


class AutomationJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runbook_id: UUID
    runbook_version: int = Field(ge=1)
    asset_id: UUID
    event_id: UUID | None = None
    inputs: dict[str, Any] = Field(default_factory=lambda: {"paths": ["/"]})


class AutomationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: str
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    agent_id: UUID
    event_id: UUID | None
    runbook_id: UUID
    runbook_version_id: UUID
    runbook_version: int
    action_id: str
    risk_level: str
    status: str
    approval_status: str
    inputs: dict[str, Any]
    sanitized_output: dict[str, Any]
    policy_snapshot: dict[str, Any]
    requested_by: UUID
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AutomationJobPage(BaseModel):
    items: list[AutomationJobResponse]
    page: int
    page_size: int
    total: int


class ApprovalDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=500)


class ApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    approval_request_id: UUID
    approver_id: UUID
    decision: str
    comment: str
    decided_at: datetime


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    approval_id: str
    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    risk_level: str
    status: str
    required_approvals: int
    requester_id: UUID
    expires_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    decisions: list[ApprovalDecisionResponse] = Field(default_factory=list)


class ApprovalPage(BaseModel):
    items: list[ApprovalResponse]
    page: int
    page_size: int
    total: int
