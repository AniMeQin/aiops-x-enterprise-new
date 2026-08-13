from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("tenant_id", "asset_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_addresses: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    operating_system: Mapped[str | None] = mapped_column(String(120), nullable=True)
    environment: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    criticality: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    gxp_classification: Mapped[str] = mapped_column(
        String(16), default="unclassified", nullable=False
    )
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    agent_status: Mapped[str] = mapped_column(String(32), default="not_installed", nullable=False)
    monitoring_status: Mapped[str] = mapped_column(
        String(32), default="not_configured", nullable=False
    )
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    custom_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AssetRelation(Base):
    __tablename__ = "asset_relations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_asset_id", "target_asset_id", "relation_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    target_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manually_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
