from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.change.infrastructure.models import ChangeRequest
from aiops_x_api.modules.cmdb.application import require_asset_refs
from aiops_x_api.modules.cmdb.contracts import AssetView
from aiops_x_api.modules.incident.contracts import require_incident_refs

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending_approval", "approved", "cancelled"},
    "pending_approval": {"approved", "rejected", "cancelled"},
    "approved": {"scheduled", "in_progress", "cancelled"},
    "scheduled": {"in_progress", "cancelled"},
    "in_progress": {"validating", "failed", "rolled_back"},
    "validating": {"completed", "failed", "rolled_back"},
    "failed": {"rolled_back"},
    "completed": set(),
    "rolled_back": set(),
    "rejected": set(),
    "cancelled": set(),
}


def human_change_number() -> str:
    return f"CHG-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"


def required_approval_count(risk_level: str, gxp_impact: bool) -> int:
    if risk_level in {"R0", "R1"} and not gxp_impact:
        return 0
    if risk_level == "R3" or gxp_impact:
        return 2
    return 1


def validate_status_transition(current: str, target: str) -> None:
    if current == target:
        return
    if target not in ALLOWED_STATUS_TRANSITIONS.get(current, set()):
        raise ApplicationError(
            code="AIOPS_8209",
            message=f"变更状态不能从 {current} 变更为 {target}",
            status_code=409,
        )


async def get_change_in_scope(
    session: AsyncSession, *, tenant_id: UUID, change_id: UUID, for_update: bool = False
) -> ChangeRequest:
    statement = select(ChangeRequest).where(
        ChangeRequest.id == change_id, ChangeRequest.tenant_id == tenant_id
    )
    if for_update:
        statement = statement.with_for_update()
    change = await session.scalar(statement)
    if change is None:
        raise ApplicationError(code="AIOPS_8204", message="变更记录不存在", status_code=404)
    return change


async def validate_change_links(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_ids: list[UUID],
    incident_ids: list[UUID],
) -> list[AssetView]:
    assets = await require_asset_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        asset_ids=asset_ids,
    )
    await require_incident_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        incident_ids=incident_ids,
    )
    return assets
