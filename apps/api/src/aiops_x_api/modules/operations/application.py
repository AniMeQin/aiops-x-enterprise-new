from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.operations.infrastructure.models import (
    Alert,
    EventAlert,
    EventTimelineEntry,
    OperationsEvent,
)


@dataclass(frozen=True)
class AIEventContext:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    evidence: dict[str, Any]


async def load_ai_event_context(
    session: AsyncSession, *, tenant_id: UUID, event_id: UUID
) -> AIEventContext:
    event = await _event_for_ai(session, tenant_id=tenant_id, event_id=event_id, lock=True)
    asset = await get_asset_for_scope(session, tenant_id=tenant_id, asset_id=event.primary_asset_id)
    alerts = (
        await session.scalars(
            select(Alert)
            .join(EventAlert, EventAlert.alert_id == Alert.id)
            .where(EventAlert.event_id == event.id)
            .order_by(Alert.starts_at.asc())
        )
    ).all()
    timeline = (
        await session.scalars(
            select(EventTimelineEntry)
            .where(EventTimelineEntry.event_id == event.id)
            .order_by(EventTimelineEntry.occurred_at.asc())
        )
    ).all()
    available_evidence_refs = {
        event.event_id,
        *(alert.alert_id for alert in alerts),
        *(
            str(reference.get("ref"))
            for alert in alerts
            for reference in alert.evidence_refs
            if reference.get("ref")
        ),
        *(
            str(reference.get("ref"))
            for entry in timeline
            for reference in entry.evidence_refs
            if reference.get("ref")
        ),
    }
    evidence = {
        "event": {
            "event_id": event.event_id,
            "title": event.title,
            "description": event.description,
            "severity": event.severity,
            "status": event.status,
            "first_seen_at": event.first_seen_at.isoformat(),
            "last_seen_at": event.last_seen_at.isoformat(),
        },
        "asset": {
            "asset_id": asset.asset_id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "monitoring_status": asset.monitoring_status,
        },
        "alerts": [
            {
                "alert_id": alert.alert_id,
                "title": alert.title,
                "description": alert.description,
                "severity": alert.severity,
                "status": alert.status,
                "labels": alert.labels,
                "evidence_refs": alert.evidence_refs,
                "duplicate_count": alert.duplicate_count,
            }
            for alert in alerts
        ],
        "timeline": [
            {
                "occurred_at": entry.occurred_at.isoformat(),
                "category": entry.category,
                "title": entry.title,
                "description": entry.description,
                "evidence_refs": entry.evidence_refs,
            }
            for entry in timeline
        ],
        "available_evidence_refs": sorted(available_evidence_refs),
    }
    return AIEventContext(
        id=event.id,
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        evidence=evidence,
    )


async def update_event_ai_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    status: str,
    summary: str | None = None,
) -> AIEventContext:
    event = await _event_for_ai(session, tenant_id=tenant_id, event_id=event_id, lock=True)
    event.ai_summary_status = status
    event.ai_summary = summary
    return AIEventContext(
        id=event.id,
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        evidence={},
    )


async def complete_event_ai_analysis(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    summary: str,
    provider: str | None,
    confidence: float,
    evidence_refs: list[dict[str, Any]],
) -> AIEventContext:
    context = await update_event_ai_state(
        session,
        tenant_id=tenant_id,
        event_id=event_id,
        status="completed",
        summary=summary,
    )
    session.add(
        EventTimelineEntry(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            event_id=context.id,
            occurred_at=datetime.now(UTC),
            category="ai",
            title="AI 事件摘要已生成",
            description=summary,
            source_type="ai_analysis",
            source_id=None,
            evidence_refs=evidence_refs,
            metadata_json={
                "provider": provider,
                "confidence": confidence,
                "recommendations_are_advisory": True,
            },
        )
    )
    return context


async def _event_for_ai(
    session: AsyncSession, *, tenant_id: UUID, event_id: UUID, lock: bool
) -> OperationsEvent:
    statement = select(OperationsEvent).where(
        OperationsEvent.id == event_id,
        OperationsEvent.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update()
    event = await session.scalar(statement)
    if event is None:
        raise ApplicationError(code="AIOPS_5104", message="事件不存在", status_code=404)
    return event
