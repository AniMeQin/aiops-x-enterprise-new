from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.incident.infrastructure.models import Incident


async def require_incident_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    incident_ids: list[UUID],
) -> None:
    if not incident_ids:
        return
    found = set(
        (
            await session.scalars(
                select(Incident.id).where(
                    Incident.id.in_(incident_ids),
                    Incident.tenant_id == tenant_id,
                    Incident.project_id == project_id,
                )
            )
        ).all()
    )
    if found != set(incident_ids):
        raise ApplicationError(
            code="AIOPS_8206",
            message="关联故障不存在或超出项目范围",
            status_code=404,
        )
