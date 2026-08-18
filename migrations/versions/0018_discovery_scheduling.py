"""Add opt-in bounded discovery scheduling.

Revision ID: 0018_discovery_scheduling
Revises: 0017_asset_components_collector_state
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_discovery_scheduling"
down_revision: str | Sequence[str] | None = "0017_asset_components_collector_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_jobs",
        sa.Column("schedule_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "discovery_jobs",
        sa.Column(
            "schedule_interval_seconds",
            sa.Integer(),
            server_default="300",
            nullable=False,
        ),
    )
    op.add_column(
        "discovery_jobs", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_discovery_jobs_next_run_at", "discovery_jobs", ["next_run_at"])
    op.create_check_constraint(
        op.f("ck_discovery_jobs_schedule_interval"),
        "discovery_jobs",
        "schedule_interval_seconds >= 300 AND schedule_interval_seconds <= 86400",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_discovery_jobs_schedule_interval"), "discovery_jobs", type_="check"
    )
    op.drop_index("ix_discovery_jobs_next_run_at", table_name="discovery_jobs")
    op.drop_column("discovery_jobs", "next_run_at")
    op.drop_column("discovery_jobs", "schedule_interval_seconds")
    op.drop_column("discovery_jobs", "schedule_enabled")
