from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class SecurityFinding(Base):
    __tablename__ = "security_findings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "external_id"),
        Index("ix_security_findings_scope_status", "tenant_id", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    finding_id: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    integration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    cve_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_data_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VulnerabilityRecord(Base):
    __tablename__ = "vulnerability_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_findings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    cvss_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cvss_vector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affected_component: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affected_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fixed_version: Mapped[str | None] = mapped_column(String(120), nullable=True)


class RemediationRecord(Base):
    __tablename__ = "remediation_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_findings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column(nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True
    )


class RiskRecord(Base):
    __tablename__ = "risk_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_findings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    likelihood: Mapped[int] = mapped_column(nullable=False)
    impact: Mapped[int] = mapped_column(nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)
    accepted: Mapped[bool] = mapped_column(default=False, nullable=False)
    accepted_by: Mapped[UUID | None] = mapped_column(nullable=True)
    acceptance_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SecurityTicket(Base):
    __tablename__ = "security_tickets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_findings.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    system: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
