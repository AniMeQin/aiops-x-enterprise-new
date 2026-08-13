"""Add versioned runbooks, policy-gated automation jobs, and approvals.

Revision ID: 0005_automation_ai_gateway
Revises: 0004_operations_events
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_automation_ai_gateway"
down_revision: str | Sequence[str] | None = "0004_operations_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runbooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "project_id", "slug"),
    )
    op.create_index("ix_runbooks_tenant_id", "runbooks", ["tenant_id"])
    op.create_index("ix_runbooks_project_id", "runbooks", ["project_id"])

    op.create_table(
        "runbook_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("runbook_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.String(length=120), nullable=False),
        sa.Column("asset_types", sa.JSON(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("retry_policy", sa.JSON(), nullable=False),
        sa.Column("idempotent", sa.Boolean(), nullable=False),
        sa.Column("pre_checks", sa.JSON(), nullable=False),
        sa.Column("execution_steps", sa.JSON(), nullable=False),
        sa.Column("post_checks", sa.JSON(), nullable=False),
        sa.Column("success_conditions", sa.JSON(), nullable=False),
        sa.Column("failure_conditions", sa.JSON(), nullable=False),
        sa.Column("rollback_steps", sa.JSON(), nullable=False),
        sa.Column("approval_policy", sa.JSON(), nullable=False),
        sa.Column("maintenance_window_required", sa.Boolean(), nullable=False),
        sa.Column("output_redaction_rules", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runbook_id"], ["runbooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("runbook_id", "version"),
    )
    op.create_index("ix_runbook_versions_runbook_id", "runbook_versions", ["runbook_id"])

    op.create_table(
        "automation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.String(length=40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("runbook_id", sa.Uuid(), nullable=False),
        sa.Column("runbook_version_id", sa.Uuid(), nullable=False),
        sa.Column("runbook_version", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("sanitized_output", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["edge_agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["operations_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runbook_id"], ["runbooks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runbook_version_id"], ["runbook_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key"),
    )
    for column in ("tenant_id", "project_id", "asset_id", "agent_id", "event_id", "runbook_id", "status"):
        op.create_index(f"ix_automation_jobs_{column}", "automation_jobs", [column])

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.String(length=40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["automation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id"),
    )
    for column in ("tenant_id", "project_id", "job_id", "status"):
        op.create_index(f"ix_approval_requests_{column}", "approval_requests", [column])

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_request_id", "approver_id"),
    )
    op.create_index(
        "ix_approval_decisions_approval_request_id",
        "approval_decisions",
        ["approval_request_id"],
    )

    op.add_column("agent_tasks", sa.Column("automation_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_tasks_automation_job_id_automation_jobs",
        "agent_tasks",
        "automation_jobs",
        ["automation_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_agent_tasks_automation_job_id", "agent_tasks", ["automation_job_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_tasks_automation_job_id", "agent_tasks", type_="unique")
    op.drop_constraint(
        "fk_agent_tasks_automation_job_id_automation_jobs", "agent_tasks", type_="foreignkey"
    )
    op.drop_column("agent_tasks", "automation_job_id")
    op.drop_table("approval_decisions")
    op.drop_table("approval_requests")
    op.drop_table("automation_jobs")
    op.drop_table("runbook_versions")
    op.drop_table("runbooks")
