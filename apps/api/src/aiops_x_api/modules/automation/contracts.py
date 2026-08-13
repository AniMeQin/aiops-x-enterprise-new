from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.automation.infrastructure.models import AutomationJob, Runbook


@dataclass(frozen=True)
class AutomationJobView:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    event_id: UUID | None
    job_id: str
    runbook_id: UUID
    runbook_version: int
    action_id: str
    risk_level: str
    status: str


async def list_event_automation_jobs(
    session: AsyncSession, *, event_id: UUID
) -> list[dict[str, object]]:
    jobs = (
        await session.scalars(
            select(AutomationJob)
            .where(AutomationJob.event_id == event_id)
            .order_by(AutomationJob.created_at.asc())
        )
    ).all()
    return [
        {
            "id": job.id,
            "job_id": job.job_id,
            "runbook_id": job.runbook_id,
            "runbook_version": job.runbook_version,
            "action_id": job.action_id,
            "risk_level": job.risk_level,
            "status": job.status,
            "approval_status": job.approval_status,
            "inputs": job.inputs,
            "sanitized_output": job.sanitized_output,
            "duration_ms": job.duration_ms,
            "created_at": job.created_at,
        }
        for job in jobs
    ]


async def cancel_queued_automation_job(
    session: AsyncSession, *, job_id: UUID, completed_at: datetime
) -> None:
    job = await session.scalar(
        select(AutomationJob).where(AutomationJob.id == job_id).with_for_update()
    )
    if job is not None and job.status == "queued":
        job.status = "canceled"
        job.completed_at = completed_at
        job.error_code = "AGENT_DISABLED"
        job.error_message = "Agent 已由管理员停用"


async def start_automation_job(
    session: AsyncSession, *, job_id: UUID, started_at: datetime
) -> AutomationJobView:
    job = await session.scalar(
        select(AutomationJob).where(AutomationJob.id == job_id).with_for_update()
    )
    if job is None or job.status != "queued":
        raise ApplicationError(code="AIOPS_6205", message="自动化任务状态冲突", status_code=409)
    job.status = "running"
    job.started_at = started_at
    return _job_view(job)


async def complete_automation_job(
    session: AsyncSession,
    *,
    job_id: UUID,
    status: str,
    started_at: datetime | None,
    completed_at: datetime,
    duration_ms: int,
    sanitized_output: dict[str, Any],
    error_code: str | None,
    error_message: str | None,
) -> AutomationJobView:
    job = await session.scalar(
        select(AutomationJob).where(AutomationJob.id == job_id).with_for_update()
    )
    if job is None:
        raise ApplicationError(code="AIOPS_6204", message="自动化任务不存在", status_code=409)
    job.status = status
    job.started_at = started_at
    job.completed_at = completed_at
    job.duration_ms = duration_ms
    job.sanitized_output = sanitized_output
    job.error_code = error_code
    job.error_message = error_message
    return _job_view(job)


def _job_view(job: AutomationJob) -> AutomationJobView:
    return AutomationJobView(
        id=job.id,
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        event_id=job.event_id,
        job_id=job.job_id,
        runbook_id=job.runbook_id,
        runbook_version=job.runbook_version,
        action_id=job.action_id,
        risk_level=job.risk_level,
        status=job.status,
    )


async def require_automation_job_ref(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    job_id: UUID | None,
) -> None:
    if job_id is None:
        return
    found = await session.scalar(
        select(AutomationJob.id).where(
            AutomationJob.id == job_id,
            AutomationJob.tenant_id == tenant_id,
            AutomationJob.project_id == project_id,
        )
    )
    if found is None:
        raise ApplicationError(
            code="AIOPS_8219",
            message="关联自动化任务不存在或超出项目范围",
            status_code=404,
        )


async def require_registered_runbook_names(
    session: AsyncSession, *, tenant_id: UUID, names: list[str]
) -> None:
    if not names:
        return
    registered = set(
        (
            await session.scalars(
                select(Runbook.name).where(
                    Runbook.tenant_id == tenant_id,
                    Runbook.name.in_(names),
                )
            )
        ).all()
    )
    if registered != set(names):
        raise ApplicationError(
            code="AIOPS_7004",
            message="AI 返回了未注册的 Runbook 推荐",
            status_code=502,
        )
