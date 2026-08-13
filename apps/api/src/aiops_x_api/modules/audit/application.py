import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.modules.audit.infrastructure.models import AuditLog, EventOutbox
from aiops_x_api.modules.identity.security import Principal


async def append_audit(
    session: AsyncSession,
    request: Request,
    *,
    action: str,
    resource_type: str,
    outcome: str,
    principal: Principal | None = None,
    actor_id: str | None = None,
    actor_type: str | None = None,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    effective_tenant_id = principal.tenant_id if principal is not None else tenant_id
    partition_key = str(effective_tenant_id) if effective_tenant_id is not None else "platform"
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:partition_key))"),
            {"partition_key": partition_key},
        )
    previous = await session.scalar(
        select(AuditLog)
        .where(AuditLog.partition_key == partition_key)
        .order_by(AuditLog.sequence_no.desc())
        .limit(1)
        .with_for_update()
    )
    sequence_no = (previous.sequence_no + 1) if previous is not None else 1
    previous_hash = previous.entry_hash if previous is not None else "0" * 64
    occurred_at = datetime.now(UTC)
    effective_actor_type = actor_type or (
        principal.auth_type if principal is not None else "anonymous"
    )
    effective_actor_id = (
        str(principal.credential_id or principal.user_id)
        if principal is not None
        else (actor_id or "unknown")
    )
    effective_metadata = {
        **(metadata or {}),
        **(
            {"authenticated_user_id": str(principal.user_id)}
            if principal is not None and principal.auth_type == "api_token"
            else {}
        ),
    }
    request_id = getattr(request.state, "request_id", "unknown")
    trace_id = getattr(request.state, "trace_id", "unknown")
    entry_hash = _audit_hash(
        {
            "partition_key": partition_key,
            "sequence_no": sequence_no,
            "previous_hash": previous_hash,
            "tenant_id": str(effective_tenant_id) if effective_tenant_id else None,
            "project_id": str(project_id) if project_id else None,
            "actor_type": effective_actor_type,
            "actor_id": effective_actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "outcome": outcome,
            "metadata": effective_metadata,
            "created_at": _utc_iso(occurred_at),
        }
    )
    entry = AuditLog(
        tenant_id=effective_tenant_id,
        project_id=project_id,
        actor_type=effective_actor_type,
        actor_id=effective_actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        trace_id=trace_id,
        outcome=outcome,
        metadata_json=effective_metadata,
        partition_key=partition_key,
        sequence_no=sequence_no,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        created_at=occurred_at,
    )
    session.add(entry)
    await session.flush()
    if effective_tenant_id is not None:
        event_id = uuid4()
        event_type = action[:160]
        session.add(
            EventOutbox(
                id=event_id,
                tenant_id=effective_tenant_id,
                project_id=project_id,
                event_type=event_type,
                subject=f"aiops.events.v1.{event_type}",
                payload={
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "event_version": 1,
                    "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
                    "tenant_id": str(effective_tenant_id),
                    "project_id": str(project_id) if project_id is not None else None,
                    "producer": "aiops-x-api",
                    "trace_id": entry.trace_id,
                    "correlation_id": resource_id,
                    "data": {
                        "audit_id": str(entry.id),
                        "actor_type": entry.actor_type,
                        "actor_id": entry.actor_id,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "outcome": outcome,
                        "metadata": metadata or {},
                    },
                },
                next_attempt_at=occurred_at,
            )
        )
    return entry


def canonical_audit_document(entry: AuditLog) -> dict[str, Any]:
    return {
        "partition_key": entry.partition_key,
        "sequence_no": entry.sequence_no,
        "previous_hash": entry.previous_hash,
        "tenant_id": str(entry.tenant_id) if entry.tenant_id else None,
        "project_id": str(entry.project_id) if entry.project_id else None,
        "actor_type": entry.actor_type,
        "actor_id": entry.actor_id,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "request_id": entry.request_id,
        "trace_id": entry.trace_id,
        "outcome": entry.outcome,
        "metadata": entry.metadata_json,
        "created_at": _utc_iso(entry.created_at),
    }


def verify_audit_entry(entry: AuditLog, expected_previous_hash: str) -> bool:
    return entry.previous_hash == expected_previous_hash and entry.entry_hash == _audit_hash(
        canonical_audit_document(entry)
    )


def _audit_hash(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _utc_iso(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()
