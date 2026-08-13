"""Add tenant plugin registry and invocation evidence.

Revision ID: 0012_plugin_registry
Revises: 0011_audit_hash_chain
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_plugin_registry"
down_revision: str | Sequence[str] | None = "0011_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugin_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("vendor", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("supported_asset_types", sa.JSON(), nullable=False),
        sa.Column("configuration_schema", sa.JSON(), nullable=False),
        sa.Column("credential_types", sa.JSON(), nullable=False),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(8), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("retry_policy", sa.JSON(), nullable=False),
        sa.Column("idempotent", sa.Boolean(), nullable=False),
        sa.Column("health_check", sa.JSON(), nullable=False),
        sa.Column("entrypoint", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "plugin_id", "version"),
    )
    op.create_index("ix_plugin_definitions_tenant_id", "plugin_definitions", ["tenant_id"])
    op.create_index("ix_plugin_definitions_plugin_id", "plugin_definitions", ["plugin_id"])
    op.create_table(
        "plugin_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("plugin_definition_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=True),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("capability", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("sanitized_output", sa.JSON(), nullable=False),
        sa.Column("raw_output_ref", sa.String(512), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plugin_definition_id"], ["plugin_definitions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "tenant_id",
        "project_id",
        "plugin_definition_id",
        "integration_id",
        "asset_id",
        "status",
    ):
        op.create_index(f"ix_plugin_invocations_{column}", "plugin_invocations", [column])
    op.create_index(
        "ix_plugin_invocations_scope_created",
        "plugin_invocations",
        ["tenant_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("plugin_invocations")
    op.drop_table("plugin_definitions")
