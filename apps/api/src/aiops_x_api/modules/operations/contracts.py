from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.operations.infrastructure.models import (
    Alert,
    EventTimelineEntry,
    MaintenanceWindow,
    OperationsEvent,
)


@dataclass(frozen=True)
class AutomationEventScope:
    id: UUID
    tenant_id: UUID
    project_id: UUID


async def require_automation_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    event_id: UUID | None,
    asset_id: UUID,
) -> AutomationEventScope | None:
    if event_id is None:
        return None
    event = await session.scalar(
        select(OperationsEvent).where(
            OperationsEvent.id == event_id,
            OperationsEvent.tenant_id == tenant_id,
            OperationsEvent.project_id == project_id,
            OperationsEvent.primary_asset_id == asset_id,
        )
    )
    if event is None:
        raise ApplicationError(
            code="AIOPS_5104", message="事件不存在或与资产范围不匹配", status_code=404
        )
    return AutomationEventScope(id=event.id, tenant_id=event.tenant_id, project_id=event.project_id)


async def maintenance_window_allows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    required: bool,
    now: datetime,
) -> bool:
    if not required:
        return True
    count = await session.scalar(
        select(func.count())
        .select_from(MaintenanceWindow)
        .where(
            MaintenanceWindow.tenant_id == tenant_id,
            MaintenanceWindow.project_id == project_id,
            MaintenanceWindow.enabled.is_(True),
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at >= now,
            (MaintenanceWindow.asset_id.is_(None)) | (MaintenanceWindow.asset_id == asset_id),
        )
    )
    return (count or 0) > 0


def append_automation_timeline(
    session: AsyncSession,
    *,
    event: AutomationEventScope,
    job_id: UUID,
    job_number: str,
    runbook_id: UUID,
    runbook_version: int,
    action_id: str,
    risk_level: str,
    status: str,
    title: str,
    occurred_at: datetime,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> None:
    session.add(
        EventTimelineEntry(
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            event_id=event.id,
            occurred_at=occurred_at,
            category="automation",
            title=title,
            description=f"{job_number} / {action_id}",
            source_type="automation_job",
            source_id=str(job_id),
            evidence_refs=evidence_refs or [],
            metadata_json={
                "job_id": job_number,
                "runbook_id": str(runbook_id),
                "runbook_version": runbook_version,
                "risk_level": risk_level,
                "status": status,
            },
        )
    )


async def require_event_ref(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    event_id: UUID | None,
) -> None:
    if event_id is None:
        return
    found = await session.scalar(
        select(OperationsEvent.id).where(
            OperationsEvent.id == event_id,
            OperationsEvent.tenant_id == tenant_id,
            OperationsEvent.project_id == project_id,
        )
    )
    if found is None:
        raise ApplicationError(code="AIOPS_8105", message="关联事件不存在", status_code=404)


async def require_alert_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    alert_ids: list[UUID],
) -> None:
    if not alert_ids:
        return
    found = set(
        (
            await session.scalars(
                select(Alert.id).where(
                    Alert.id.in_(alert_ids),
                    Alert.tenant_id == tenant_id,
                    Alert.project_id == project_id,
                )
            )
        ).all()
    )
    if found != set(alert_ids):
        raise ApplicationError(
            code="AIOPS_8106",
            message="关联告警不存在或超出项目范围",
            status_code=404,
        )
