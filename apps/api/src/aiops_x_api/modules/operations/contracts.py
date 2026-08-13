from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.operations.infrastructure.models import Alert, OperationsEvent


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
