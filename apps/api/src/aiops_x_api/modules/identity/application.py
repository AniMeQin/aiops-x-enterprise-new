from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.identity.infrastructure.models import User


async def require_active_user_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_ids: list[UUID],
) -> None:
    if not user_ids:
        return
    found = set(
        (
            await session.scalars(
                select(User.id).where(
                    User.id.in_(user_ids),
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                )
            )
        ).all()
    )
    if found != set(user_ids):
        raise ApplicationError(
            code="AIOPS_2110",
            message="关联用户不存在、已停用或超出租户范围",
            status_code=404,
        )
