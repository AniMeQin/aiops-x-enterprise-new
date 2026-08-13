"""Add phase-two service management, knowledge and reliability domains.

Revision ID: 0009_phase2_operations
Revises: 0008_agent_certificate_renewal
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0009_phase2_operations"
down_revision: str | Sequence[str] | None = "0008_agent_certificate_renewal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "evidence_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("object_ref", sa.String(512), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("gxp_classification", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "evidence_id"),
    )
    op.create_index("ix_evidence_records_tenant_id", "evidence_records", ["tenant_id"])
    op.create_index("ix_evidence_records_project_id", "evidence_records", ["project_id"])
    op.create_index("ix_evidence_records_asset_id", "evidence_records", ["asset_id"])
    op.create_index("ix_evidence_records_evidence_type", "evidence_records", ["evidence_type"])
    op.create_index("ix_evidence_records_classification", "evidence_records", ["classification"])
    op.create_index("ix_evidence_records_gxp_classification", "evidence_records", ["gxp_classification"])
    op.create_index("ix_evidence_records_observed_at", "evidence_records", ["observed_at"])
    op.create_index(
        "ix_evidence_scope_observed", "evidence_records", ["tenant_id", "project_id", "observed_at"]
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_number", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("participant_ids", sa.JSON(), nullable=False),
        sa.Column("impact_scope", sa.JSON(), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("alert_ids", sa.JSON(), nullable=False),
        sa.Column("change_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("root_cause_candidates", sa.JSON(), nullable=False),
        sa.Column("resolution_steps", sa.JSON(), nullable=False),
        sa.Column("approval_refs", sa.JSON(), nullable=False),
        sa.Column("sla_policy", sa.JSON(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "incident_number"),
    )
    for column in ("tenant_id", "project_id", "source_event_id", "severity", "status", "owner_id"):
        op.create_index(f"ix_incidents_{column}", "incidents", [column])
    op.create_index(
        "ix_incidents_scope_status_created",
        "incidents",
        ["tenant_id", "project_id", "status", "created_at"],
    )
    op.create_table(
        "incident_timeline_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "project_id", "incident_id"):
        op.create_index(f"ix_incident_timeline_entries_{column}", "incident_timeline_entries", [column])
    op.create_index(
        "ix_incident_timeline_order", "incident_timeline_entries", ["incident_id", "occurred_at"]
    )
    op.create_table(
        "incident_postmortems",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("customer_impact", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("detection", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("lessons_learned", sa.Text(), nullable=False),
        sa.Column("action_items", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("report_object_ref", sa.String(512), nullable=True),
        sa.Column("generated_by", sa.String(24), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    for column in ("tenant_id", "project_id", "incident_id"):
        op.create_index(f"ix_incident_postmortems_{column}", "incident_postmortems", [column])

    op.create_table(
        "change_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("change_number", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("risk_level", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("gxp_impact", sa.Boolean(), nullable=False),
        sa.Column("affected_asset_ids", sa.JSON(), nullable=False),
        sa.Column("incident_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("implementation_plan", sa.JSON(), nullable=False),
        sa.Column("precheck_plan", sa.JSON(), nullable=False),
        sa.Column("validation_plan", sa.JSON(), nullable=False),
        sa.Column("success_criteria", sa.JSON(), nullable=False),
        sa.Column("rollback_plan", sa.JSON(), nullable=False),
        sa.Column("impact_analysis", sa.JSON(), nullable=False),
        sa.Column("approval_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("configuration_backup_ref", sa.String(512), nullable=True),
        sa.Column("automation_job_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "change_number"),
    )
    for column in ("tenant_id", "project_id", "risk_level", "status", "automation_job_id"):
        op.create_index(f"ix_change_requests_{column}", "change_requests", [column])
    op.create_index(
        "ix_changes_scope_status_schedule",
        "change_requests",
        ["tenant_id", "project_id", "status", "scheduled_start"],
    )
    op.create_table(
        "change_approval_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_id", "approver_id"),
    )
    for column in ("change_id", "tenant_id", "approver_id"):
        op.create_index(f"ix_change_approval_decisions_{column}", "change_approval_decisions", [column])
    op.create_table(
        "change_timeline_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("change_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["change_id"], ["change_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_timeline_entries_change_id", "change_timeline_entries", ["change_id"])
    op.create_index("ix_change_timeline_entries_tenant_id", "change_timeline_entries", ["tenant_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("object_ref", sa.String(512), nullable=True),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("gxp_classification", sa.String(16), nullable=False),
        sa.Column("allowed_role_names", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("indexing_error", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "document_id"),
    )
    for column in ("tenant_id", "project_id", "status", "classification", "gxp_classification"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])
    op.create_index(
        "ix_knowledge_scope_status", "knowledge_documents", ["tenant_id", "project_id", "status"]
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index"),
    )
    for column in ("tenant_id", "project_id", "document_id"):
        op.create_index(f"ix_knowledge_chunks_{column}", "knowledge_chunks", [column])
    op.create_index(
        "ix_knowledge_chunks_scope", "knowledge_chunks", ["tenant_id", "project_id", "document_id"]
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON knowledge_chunks "
            "USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
        )

    op.create_table(
        "service_level_objectives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("service_ref", sa.String(255), nullable=False),
        sa.Column("sli_type", sa.String(32), nullable=False),
        sa.Column("prometheus_query", sa.Text(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("warning_burn_rate", sa.Float(), nullable=False),
        sa.Column("critical_burn_rate", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "project_id", "name"),
    )
    for column in ("tenant_id", "project_id"):
        op.create_index(f"ix_service_level_objectives_{column}", "service_level_objectives", [column])
    op.create_index(
        "ix_slo_scope_enabled", "service_level_objectives", ["tenant_id", "project_id", "enabled"]
    )
    op.create_table(
        "slo_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("slo_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("indicator_value", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("error_budget_remaining", sa.Float(), nullable=False),
        sa.Column("burn_rate", sa.Float(), nullable=False),
        sa.Column("query_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("raw_sample", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["slo_id"], ["service_level_objectives.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "project_id", "slo_id"):
        op.create_index(f"ix_slo_evaluations_{column}", "slo_evaluations", [column])
    op.create_index("ix_slo_evaluations_order", "slo_evaluations", ["slo_id", "evaluated_at"])
    op.create_table(
        "capacity_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(48), nullable=False),
        sa.Column("service_ref", sa.String(255), nullable=False),
        sa.Column("prometheus_query", sa.Text(), nullable=False),
        sa.Column("lookback_hours", sa.Integer(), nullable=False),
        sa.Column("forecast_hours", sa.Integer(), nullable=False),
        sa.Column("warning_threshold", sa.Float(), nullable=False),
        sa.Column("critical_threshold", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("source_ref", sa.String(512), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id"),
    )
    for column in ("tenant_id", "project_id"):
        op.create_index(f"ix_capacity_analyses_{column}", "capacity_analyses", [column])
    op.create_index(
        "ix_capacity_scope_created", "capacity_analyses", ["tenant_id", "project_id", "created_at"]
    )

    op.create_table(
        "generated_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("report_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("object_ref", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("generation_metadata", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "report_id"),
    )
    for column in ("tenant_id", "project_id", "source_id", "status"):
        op.create_index(f"ix_generated_reports_{column}", "generated_reports", [column])
    op.create_index(
        "ix_reports_scope_created", "generated_reports", ["tenant_id", "project_id", "created_at"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("generated_reports")
    op.drop_table("capacity_analyses")
    op.drop_table("slo_evaluations")
    op.drop_table("service_level_objectives")
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.drop_table("change_timeline_entries")
    op.drop_table("change_approval_decisions")
    op.drop_table("change_requests")
    op.drop_table("incident_postmortems")
    op.drop_table("incident_timeline_entries")
    op.drop_table("incidents")
    op.drop_table("evidence_records")
