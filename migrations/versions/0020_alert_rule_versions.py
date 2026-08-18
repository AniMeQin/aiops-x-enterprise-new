"""Add versioned managed alert rules.

Revision ID: 0020_alert_rule_versions
Revises: 0019_alert_lifecycle
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_alert_rule_versions"
down_revision: str | Sequence[str] | None = "0019_alert_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "project_id", "slug"),
    )
    op.create_index("ix_alert_rules_tenant_id", "alert_rules", ["tenant_id"])
    op.create_index("ix_alert_rules_project_id", "alert_rules", ["project_id"])
    op.create_table(
        "alert_rule_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_rule_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metric_key", sa.String(32), nullable=False),
        sa.Column("operator", sa.String(4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alert_rule_id", "version"),
    )
    op.create_index(
        "ix_alert_rule_versions_alert_rule_id", "alert_rule_versions", ["alert_rule_id"]
    )
    op.create_index("ix_alert_rule_versions_status", "alert_rule_versions", ["status"])


def downgrade() -> None:
    op.drop_table("alert_rule_versions")
    op.drop_table("alert_rules")
