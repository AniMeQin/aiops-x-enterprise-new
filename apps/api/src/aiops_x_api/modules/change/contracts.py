from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.change.infrastructure.models import ChangeRequest


async def require_change_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    change_ids: list[UUID],
) -> None:
    if not change_ids:
        return
    found = set(
        (
            await session.scalars(
                select(ChangeRequest.id).where(
                    ChangeRequest.id.in_(change_ids),
                    ChangeRequest.tenant_id == tenant_id,
                    ChangeRequest.project_id == project_id,
                )
            )
        ).all()
    )
    if found != set(change_ids):
        raise ApplicationError(
            code="AIOPS_8107",
            message="关联变更不存在或超出项目范围",
            status_code=404,
        )
