"""Add previous Agent certificate overlap for reliable renewal.

Revision ID: 0008_agent_certificate_renewal
Revises: 0007_event_outbox
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_certificate_renewal"
down_revision: str | Sequence[str] | None = "0007_event_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "edge_agents",
        sa.Column("previous_certificate_serial", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "edge_agents",
        sa.Column("previous_certificate_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "edge_agents",
        sa.Column("previous_certificate_not_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "edge_agents",
        sa.Column("last_renewal_csr_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_edge_agents_previous_certificate_serial",
        "edge_agents",
        ["previous_certificate_serial"],
    )


def downgrade() -> None:
    op.drop_index("ix_edge_agents_previous_certificate_serial", table_name="edge_agents")
    op.drop_column("edge_agents", "last_renewal_csr_fingerprint")
    op.drop_column("edge_agents", "previous_certificate_not_after")
    op.drop_column("edge_agents", "previous_certificate_fingerprint")
    op.drop_column("edge_agents", "previous_certificate_serial")
