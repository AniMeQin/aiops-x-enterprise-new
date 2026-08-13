"""Add normalized security finding, vulnerability, remediation, risk and ticket data.

Revision ID: 0014_security_center
Revises: 0013_agent_lifecycle
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_security_center"
down_revision: str | Sequence[str] | None = "0013_agent_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.String(48), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid()),
        sa.Column("integration_id", sa.Uuid()),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cve_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("raw_data_ref", sa.String(512)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id"),
        sa.UniqueConstraint("tenant_id", "source", "external_id"),
    )
    for column in ("tenant_id", "project_id", "asset_id", "integration_id", "fingerprint", "severity", "status"):
        op.create_index(f"ix_security_findings_{column}", "security_findings", [column])
    op.create_index("ix_security_findings_scope_status", "security_findings", ["tenant_id", "project_id", "status"])
    op.create_table(
        "vulnerability_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finding_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("cvss_score", sa.Float()),
        sa.Column("cvss_vector", sa.String(255)),
        sa.Column("affected_component", sa.String(255)),
        sa.Column("affected_version", sa.String(120)),
        sa.Column("fixed_version", sa.String(120)),
        sa.ForeignKeyConstraint(["finding_id"], ["security_findings.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "remediation_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finding_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid()),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("change_id", sa.Uuid()),
        sa.ForeignKeyConstraint(["finding_id"], ["security_findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "risk_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finding_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("likelihood", sa.Integer(), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("accepted_by", sa.Uuid()),
        sa.Column("acceptance_reason", sa.String(500)),
        sa.ForeignKeyConstraint(["finding_id"], ["security_findings.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "security_tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finding_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("system", sa.String(80), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("external_url", sa.String(512)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["security_findings.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("security_tickets")
    op.drop_table("risk_records")
    op.drop_table("remediation_records")
    op.drop_table("vulnerability_records")
    op.drop_table("security_findings")
