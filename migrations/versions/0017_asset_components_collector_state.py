"""Add asset inventory detail and persistent collector state.

Revision ID: 0017_asset_components_collector_state
Revises: 0016_discovery_control_plane
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_asset_components_collector_state"
down_revision: str | Sequence[str] | None = "0016_discovery_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("operating_system_version", sa.String(120)))
    op.add_column("assets", sa.Column("business_service", sa.String(160)))
    op.add_column("assets", sa.Column("discovery_source", sa.String(120)))
    op.add_column(
        "assets",
        sa.Column("discovery_status", sa.String(32), server_default="manual", nullable=False),
    )
    op.add_column("assets", sa.Column("last_connected_at", sa.DateTime(timezone=True)))
    op.add_column("assets", sa.Column("last_monitored_at", sa.DateTime(timezone=True)))
    op.create_table(
        "asset_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("parent_component_id", sa.Uuid()),
        sa.Column("component_type", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_component_id"], ["asset_components.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "component_type", "external_id"),
    )
    for column in ("tenant_id", "project_id", "asset_id", "parent_component_id", "component_type"):
        op.create_index(f"ix_asset_components_{column}", "asset_components", [column])
    op.create_index(
        "ix_asset_components_scope_type",
        "asset_components",
        ["tenant_id", "project_id", "component_type"],
    )
    op.create_table(
        "collector_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("monitor_target_id", sa.Uuid(), nullable=False),
        sa.Column("collector_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_sample_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["monitor_target_id"], ["monitor_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "collector_type"),
        sa.UniqueConstraint("monitor_target_id"),
    )
    for column in ("tenant_id", "project_id", "asset_id", "status"):
        op.create_index(f"ix_collector_states_{column}", "collector_states", [column])
    op.create_index(
        "ix_collector_states_scope_status",
        "collector_states",
        ["tenant_id", "project_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("collector_states")
    op.drop_table("asset_components")
    op.drop_column("assets", "last_monitored_at")
    op.drop_column("assets", "last_connected_at")
    op.drop_column("assets", "discovery_status")
    op.drop_column("assets", "discovery_source")
    op.drop_column("assets", "business_service")
    op.drop_column("assets", "operating_system_version")
