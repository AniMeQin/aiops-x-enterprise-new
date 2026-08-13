from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.integrations.infrastructure.models import Integration


@dataclass(frozen=True)
class IntegrationConnection:
    id: UUID
    tenant_id: UUID
    project_id: UUID | None
    integration_type: str
    endpoint: str
    credential_ref: str | None
    configuration: dict[str, Any]
    capabilities: tuple[str, ...]


async def get_integration_connection(
    session: AsyncSession, *, tenant_id: UUID, integration_id: UUID
) -> IntegrationConnection:
    integration = await session.scalar(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.tenant_id == tenant_id,
            Integration.enabled.is_(True),
        )
    )
    if integration is None:
        raise ApplicationError(code="AIOPS_7104", message="集成不存在或已停用", status_code=404)
    return IntegrationConnection(
        id=integration.id,
        tenant_id=integration.tenant_id,
        project_id=integration.project_id,
        integration_type=integration.integration_type,
        endpoint=integration.endpoint,
        credential_ref=integration.credential_ref,
        configuration=integration.configuration,
        capabilities=tuple(integration.capabilities),
    )
