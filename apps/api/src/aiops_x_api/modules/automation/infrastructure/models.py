from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class Runbook(Base):
    __tablename__ = "runbooks"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "slug"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="published", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RunbookVersion(Base):
    __tablename__ = "runbook_versions"
    __table_args__ = (UniqueConstraint("runbook_id", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    runbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("runbooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    required_permissions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pre_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    execution_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    post_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    success_conditions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    failure_conditions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rollback_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    approval_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    maintenance_window_required: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    output_redaction_rules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AutomationJob(Base):
    __tablename__ = "automation_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("edge_agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("operations_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    runbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("runbooks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    runbook_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("runbook_versions.id", ondelete="RESTRICT"), nullable=False
    )
    runbook_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sanitized_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    approval_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("automation_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (UniqueConstraint("approval_request_id", "approver_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    approval_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
