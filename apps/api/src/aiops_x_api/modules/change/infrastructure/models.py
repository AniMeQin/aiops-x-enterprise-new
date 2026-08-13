from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "change_number"),
        Index(
            "ix_changes_scope_status_schedule",
            "tenant_id",
            "project_id",
            "status",
            "scheduled_start",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    change_number: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    gxp_impact: Mapped[bool] = mapped_column(default=False, nullable=False)
    affected_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    incident_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    implementation_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    precheck_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    validation_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    success_criteria: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    rollback_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    impact_analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    approval_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    required_approvals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration_backup_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    automation_job_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    requested_by: Mapped[UUID] = mapped_column(nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChangeApprovalDecision(Base):
    __tablename__ = "change_approval_decisions"
    __table_args__ = (UniqueConstraint("change_id", "approver_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    change_id: Mapped[UUID] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    approver_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    comment: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChangeTimelineEntry(Base):
    __tablename__ = "change_timeline_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    change_id: Mapped[UUID] = mapped_column(
        ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
