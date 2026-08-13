from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
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


class ServiceLevelObjective(Base):
    __tablename__ = "service_level_objectives"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "name"),
        Index("ix_slo_scope_enabled", "tenant_id", "project_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    service_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    sli_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prometheus_query: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_burn_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    critical_burn_rate: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SloEvaluation(Base):
    __tablename__ = "slo_evaluations"
    __table_args__ = (Index("ix_slo_evaluations_order", "slo_id", "evaluated_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    slo_id: Mapped[UUID] = mapped_column(
        ForeignKey("service_level_objectives.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    indicator_value: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    error_budget_remaining: Mapped[float] = mapped_column(Float, nullable=False)
    burn_rate: Mapped[float] = mapped_column(Float, nullable=False)
    query_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_sample: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CapacityAnalysis(Base):
    __tablename__ = "capacity_analyses"
    __table_args__ = (Index("ix_capacity_scope_created", "tenant_id", "project_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(48), nullable=False)
    service_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    prometheus_query: Mapped[str] = mapped_column(Text, nullable=False)
    lookback_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    critical_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
