"""Add transactional event outbox for JetStream publication.

Revision ID: 0007_event_outbox
Revises: 0006_integrations_management
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_event_outbox"
down_revision: str | Sequence[str] | None = "0006_integrations_management"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_outbox_tenant_id", "event_outbox", ["tenant_id"])
    op.create_index("ix_event_outbox_project_id", "event_outbox", ["project_id"])
    op.create_index("ix_event_outbox_event_type", "event_outbox", ["event_type"])
    op.create_index("ix_event_outbox_status", "event_outbox", ["status"])
    op.create_index("ix_event_outbox_next_attempt_at", "event_outbox", ["next_attempt_at"])
    op.create_index("ix_event_outbox_created_at", "event_outbox", ["created_at"])


def downgrade() -> None:
    op.drop_table("event_outbox")
