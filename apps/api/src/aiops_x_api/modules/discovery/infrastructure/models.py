from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class DiscoveryJob(Base):
    __tablename__ = "discovery_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "name"),
        CheckConstraint(
            "schedule_interval_seconds >= 300 AND schedule_interval_seconds <= 86400",
            name="schedule_interval",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    discovery_type: Mapped[str] = mapped_column(String(32), default="private_tcp", nullable=False)
    networks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    ports: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    max_hosts: Mapped[int] = mapped_column(Integer, default=256, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    schedule_interval_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_status: Mapped[str] = mapped_column(String(24), default="never", nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    discovery_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False, index=True)
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    observed_host_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "fingerprint"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    discovery_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="RESTRICT"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    observed_ports: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    match_status: Mapped[str] = mapped_column(String(24), default="none", nullable=False)
    matched_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
