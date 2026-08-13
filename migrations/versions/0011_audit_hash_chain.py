"""Add tamper-evident audit hash chain and archive metadata.

Revision ID: 0011_audit_hash_chain
Revises: 0010_enterprise_identity
Create Date: 2026-08-13
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import context, op

revision: str = "0011_audit_hash_chain"
down_revision: str | Sequence[str] | None = "0010_enterprise_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("partition_key", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("sequence_no", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("entry_hash", sa.String(64), nullable=True))
    op.add_column("audit_logs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_logs", sa.Column("archive_object_ref", sa.String(512), nullable=True))
    if context.is_offline_mode():
        # The chain must incorporate existing row values in deterministic order.
        # A static SQL renderer has no access to those values; fail closed if the
        # generated script is ever executed instead of silently creating gaps.
        op.execute(
            "DO $$ BEGIN RAISE EXCEPTION "
            "'0011_audit_hash_chain requires an online transactional Alembic migration'; "
            "END $$"
        )
        return
    bind = op.get_bind()
    # 0001 makes audit_logs append-only. The online backfill is the sole
    # controlled exception: disable only that named trigger inside the same
    # transactional migration, populate the deterministic chain, then restore
    # append-only enforcement before adding the final constraints.
    op.execute("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_append_only")
    rows = bind.execute(
        sa.text(
            "SELECT id, tenant_id, project_id, actor_type, actor_id, action, resource_type, "
            "resource_id, request_id, trace_id, outcome, metadata_json, created_at "
            "FROM audit_logs ORDER BY tenant_id NULLS FIRST, created_at, id"
        )
    ).mappings()
    sequence_by_partition: dict[str, int] = defaultdict(int)
    previous_by_partition: dict[str, str] = defaultdict(lambda: "0" * 64)
    for row in rows:
        partition = str(row["tenant_id"]) if row["tenant_id"] is not None else "platform"
        sequence_by_partition[partition] += 1
        sequence = sequence_by_partition[partition]
        previous_hash = previous_by_partition[partition]
        document = {
            "partition_key": partition,
            "sequence_no": sequence,
            "previous_hash": previous_hash,
            "tenant_id": str(row["tenant_id"]) if row["tenant_id"] is not None else None,
            "project_id": str(row["project_id"]) if row["project_id"] is not None else None,
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "request_id": row["request_id"],
            "trace_id": row["trace_id"],
            "outcome": row["outcome"],
            "metadata": row["metadata_json"],
            "created_at": _utc_iso(row["created_at"]),
        }
        entry_hash = hashlib.sha256(
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE audit_logs SET partition_key=:partition, sequence_no=:sequence, "
                "previous_hash=:previous_hash, entry_hash=:entry_hash WHERE id=:id"
            ),
            {
                "partition": partition,
                "sequence": sequence,
                "previous_hash": previous_hash,
                "entry_hash": entry_hash,
                "id": row["id"],
            },
        )
        previous_by_partition[partition] = entry_hash
    op.execute("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_append_only")
    op.alter_column("audit_logs", "partition_key", nullable=False)
    op.alter_column("audit_logs", "sequence_no", nullable=False)
    op.alter_column("audit_logs", "previous_hash", nullable=False)
    op.alter_column("audit_logs", "entry_hash", nullable=False)
    op.create_index("ix_audit_logs_partition_key", "audit_logs", ["partition_key"])
    op.create_index("ix_audit_logs_entry_hash", "audit_logs", ["entry_hash"])
    op.create_unique_constraint(
        "uq_audit_logs_partition_sequence", "audit_logs", ["partition_key", "sequence_no"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_audit_logs_partition_sequence", "audit_logs", type_="unique")
    op.drop_index("ix_audit_logs_entry_hash", table_name="audit_logs")
    op.drop_index("ix_audit_logs_partition_key", table_name="audit_logs")
    op.drop_column("audit_logs", "archive_object_ref")
    op.drop_column("audit_logs", "archived_at")
    op.drop_column("audit_logs", "entry_hash")
    op.drop_column("audit_logs", "previous_hash")
    op.drop_column("audit_logs", "sequence_no")
    op.drop_column("audit_logs", "partition_key")


def _utc_iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value)
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()
