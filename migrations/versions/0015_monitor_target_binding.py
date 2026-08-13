"""Add explicit, unique asset to Prometheus target bindings.

Revision ID: 0015_monitor_target_binding
Revises: 0014_security_center
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_monitor_target_binding"
down_revision: str | Sequence[str] | None = "0014_security_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitor_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("prometheus_job", sa.String(120), nullable=False),
        sa.Column("prometheus_instance", sa.String(255), nullable=False),
        sa.Column("tenant_slug", sa.String(80), nullable=False),
        sa.Column("project_slug", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "prometheus_job", "prometheus_instance"
        ),
    )
    for column in ("tenant_id", "project_id"):
        op.create_index(f"ix_monitor_targets_{column}", "monitor_targets", [column])
    op.create_index(
        "ix_monitor_targets_scope_enabled",
        "monitor_targets",
        ["tenant_id", "project_id", "enabled"],
    )
    op.create_table(
        "asset_monitor_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("monitor_target_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("identity_label", sa.String(64), nullable=False),
        sa.Column("identity_value", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("verification_status", sa.String(24), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["monitor_target_id"], ["monitor_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "purpose"),
        sa.UniqueConstraint("monitor_target_id"),
    )
    for column in ("tenant_id", "project_id", "asset_id", "monitor_target_id", "verification_status"):
        op.create_index(f"ix_asset_monitor_bindings_{column}", "asset_monitor_bindings", [column])
    op.create_index(
        "ix_asset_monitor_bindings_scope_status",
        "asset_monitor_bindings",
        ["tenant_id", "project_id", "verification_status"],
    )


def downgrade() -> None:
    op.drop_table("asset_monitor_bindings")
    op.drop_table("monitor_targets")
