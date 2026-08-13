from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.automation.infrastructure.models import AutomationJob


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
