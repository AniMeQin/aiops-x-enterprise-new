"""Add auditable Agent disable and replacement lifecycle.

Revision ID: 0013_agent_lifecycle
Revises: 0012_plugin_registry
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_agent_lifecycle"
down_revision: str | Sequence[str] | None = "0012_plugin_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("edge_agents", sa.Column("disabled_at", sa.DateTime(timezone=True)))
    op.add_column("edge_agents", sa.Column("disabled_by", sa.Uuid()))
    op.add_column("edge_agents", sa.Column("disable_reason", sa.String(500)))
    op.create_foreign_key(
        "fk_edge_agents_disabled_by_users",
        "edge_agents",
        "users",
        ["disabled_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    # 0003 is rendered with the repository-wide SQLAlchemy naming convention,
    # therefore the original multi-column constraint is named from its first
    # column instead of PostgreSQL's implicit ``<table>_<columns>_key`` form.
    op.drop_constraint("uq_edge_agents_tenant_id", "edge_agents", type_="unique")
    op.create_index(
        "uq_edge_agents_active_asset",
        "edge_agents",
        ["tenant_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disabled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_edge_agents_active_asset", table_name="edge_agents")
    op.create_unique_constraint(
        "uq_edge_agents_tenant_id", "edge_agents", ["tenant_id", "asset_id"]
    )
    op.drop_constraint("fk_edge_agents_disabled_by_users", "edge_agents", type_="foreignkey")
    op.drop_column("edge_agents", "disable_reason")
    op.drop_column("edge_agents", "disabled_by")
    op.drop_column("edge_agents", "disabled_at")
