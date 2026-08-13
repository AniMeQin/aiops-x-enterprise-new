from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.tenant.infrastructure.models import Project


async def get_project_in_tenant(
    session: AsyncSession, tenant_id: UUID, project_id: UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    if project is None:
        raise ApplicationError(code="AIOPS_3004", message="项目不存在", status_code=404)
    return project
