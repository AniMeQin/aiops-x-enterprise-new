from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.change.contracts import require_change_refs
from aiops_x_api.modules.cmdb.application import require_asset_refs
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.incident.infrastructure.models import (
    Incident,
    IncidentPostmortem,
    IncidentTimelineEntry,
)
from aiops_x_api.modules.operations.contracts import require_alert_refs, require_event_ref

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"acknowledged", "investigating", "cancelled"},
    "acknowledged": {"investigating", "mitigated", "cancelled"},
    "investigating": {"mitigated", "resolved", "cancelled"},
    "mitigated": {"investigating", "resolved"},
    "resolved": {"investigating", "closed"},
    "closed": set(),
    "cancelled": set(),
}


def human_incident_number() -> str:
    return f"INC-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"


def validate_transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ApplicationError(
            code="AIOPS_8109",
            message=f"故障状态不能从 {current} 变更为 {target}",
            status_code=409,
        )


async def get_incident_in_scope(
    session: AsyncSession, *, tenant_id: UUID, incident_id: UUID, for_update: bool = False
) -> Incident:
    statement = select(Incident).where(Incident.id == incident_id, Incident.tenant_id == tenant_id)
    if for_update:
        statement = statement.with_for_update()
    incident = await session.scalar(statement)
    if incident is None:
        raise ApplicationError(code="AIOPS_8104", message="故障记录不存在", status_code=404)
    return incident


async def incident_report_data(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, incident_id: UUID
) -> dict[str, object]:
    incident = await get_incident_in_scope(session, tenant_id=tenant_id, incident_id=incident_id)
    if incident.project_id != project_id:
        raise ApplicationError(code="AIOPS_8104", message="故障记录不存在", status_code=404)
    timeline = (
        await session.scalars(
            select(IncidentTimelineEntry)
            .where(IncidentTimelineEntry.incident_id == incident.id)
            .order_by(IncidentTimelineEntry.occurred_at)
        )
    ).all()
    postmortem = await session.scalar(
        select(IncidentPostmortem).where(IncidentPostmortem.incident_id == incident.id)
    )
    return {
        "incident": {
            "incident_number": incident.incident_number,
            "title": incident.title,
            "description": incident.description,
            "severity": incident.severity,
            "status": incident.status,
            "impact_scope": incident.impact_scope,
            "asset_ids": incident.asset_ids,
            "evidence_ids": incident.evidence_ids,
            "created_at": incident.created_at.isoformat(),
            "acknowledged_at": (
                incident.acknowledged_at.isoformat() if incident.acknowledged_at else None
            ),
            "restored_at": incident.restored_at.isoformat() if incident.restored_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        "timeline": [
            {
                "occurred_at": row.occurred_at.isoformat(),
                "entry_type": row.entry_type,
                "title": row.title,
                "description": row.description,
                "evidence_ids": row.evidence_ids,
            }
            for row in timeline
        ],
        "postmortem": (
            {
                "status": postmortem.status,
                "summary": postmortem.summary,
                "customer_impact": postmortem.customer_impact,
                "root_cause": postmortem.root_cause,
                "lessons_learned": postmortem.lessons_learned,
                "action_items": postmortem.action_items,
                "evidence_ids": postmortem.evidence_ids,
            }
            if postmortem is not None
            else None
        ),
    }


async def validate_incident_links(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    source_event_id: UUID | None,
    asset_ids: list[UUID],
    alert_ids: list[UUID],
    change_ids: list[UUID],
) -> list[Asset]:
    await require_event_ref(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        event_id=source_event_id,
    )
    assets = await require_asset_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        asset_ids=asset_ids,
    )
    await require_alert_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        alert_ids=alert_ids,
    )
    await require_change_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        change_ids=change_ids,
    )
    return assets
