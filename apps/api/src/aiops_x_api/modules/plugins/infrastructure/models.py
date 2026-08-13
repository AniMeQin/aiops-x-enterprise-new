from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from aiops_x_api.core.database import Base


class PluginDefinition(Base):
    __tablename__ = "plugin_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "plugin_id", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plugin_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    vendor: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    supported_asset_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    configuration_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    credential_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    required_permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(nullable=False)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotent: Mapped[bool] = mapped_column(nullable=False)
    health_check: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PluginInvocation(Base):
    __tablename__ = "plugin_invocations"
    __table_args__ = (
        Index("ix_plugin_invocations_scope_created", "tenant_id", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    plugin_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("plugin_definitions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    integration_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    asset_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    sanitized_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_output_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
