from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "incident_number"),
        Index(
            "ix_incidents_scope_status_created", "tenant_id", "project_id", "status", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_number: Mapped[str] = mapped_column(String(40), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_event_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    owner_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    participant_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    impact_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    alert_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    change_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    root_cause_candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    resolution_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    approval_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sla_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IncidentTimelineEntry(Base):
    __tablename__ = "incident_timeline_entries"
    __table_args__ = (Index("ix_incident_timeline_order", "incident_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IncidentPostmortem(Base):
    __tablename__ = "incident_postmortems"
    __table_args__ = (UniqueConstraint("incident_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    customer_impact: Mapped[str] = mapped_column(Text, default="", nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trigger: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detection: Mapped[str] = mapped_column(Text, default="", nullable=False)
    response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    resolution: Mapped[str] = mapped_column(Text, default="", nullable=False)
    lessons_learned: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    report_object_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_by: Mapped[str] = mapped_column(String(24), default="human", nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
