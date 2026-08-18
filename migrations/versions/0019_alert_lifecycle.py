"""Add accountable alert lifecycle and timeline.

Revision ID: 0019_alert_lifecycle
Revises: 0018_discovery_scheduling
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_alert_lifecycle"
down_revision: str | Sequence[str] | None = "0018_discovery_scheduling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("assigned_to", sa.Uuid()))
    op.add_column("alerts", sa.Column("acknowledged_by", sa.Uuid()))
    op.add_column("alerts", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column("alerts", sa.Column("closed_by", sa.Uuid()))
    op.add_column("alerts", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("alerts", sa.Column("resolution_summary", sa.Text()))
    op.add_column(
        "alerts", sa.Column("reopened_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_foreign_key(
        "fk_alerts_assigned_to_users",
        "alerts",
        "users",
        ["assigned_to"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_alerts_acknowledged_by_users",
        "alerts",
        "users",
        ["acknowledged_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_alerts_closed_by_users",
        "alerts",
        "users",
        ["closed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_alerts_assigned_to", "alerts", ["assigned_to"])
    op.create_table(
        "alert_timeline_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=False),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "project_id", "alert_id", "occurred_at"):
        op.create_index(
            f"ix_alert_timeline_entries_{column}", "alert_timeline_entries", [column]
        )


def downgrade() -> None:
    op.drop_table("alert_timeline_entries")
    op.drop_index("ix_alerts_assigned_to", table_name="alerts")
    op.drop_constraint("fk_alerts_closed_by_users", "alerts", type_="foreignkey")
    op.drop_constraint("fk_alerts_acknowledged_by_users", "alerts", type_="foreignkey")
    op.drop_constraint("fk_alerts_assigned_to_users", "alerts", type_="foreignkey")
    op.drop_column("alerts", "reopened_count")
    op.drop_column("alerts", "resolution_summary")
    op.drop_column("alerts", "closed_at")
    op.drop_column("alerts", "closed_by")
    op.drop_column("alerts", "acknowledged_at")
    op.drop_column("alerts", "acknowledged_by")
    op.drop_column("alerts", "assigned_to")
