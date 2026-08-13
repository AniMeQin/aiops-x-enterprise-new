from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.agent_control.infrastructure.models import AgentTask, EdgeAgent


@dataclass(frozen=True)
class AgentExecutionTarget:
    id: UUID
    capabilities: dict[str, Any]


async def require_online_agent_for_asset(
    session: AsyncSession, *, tenant_id: UUID, asset_id: UUID
) -> AgentExecutionTarget:
    agent = await session.scalar(
        select(EdgeAgent).where(
            EdgeAgent.asset_id == asset_id,
            EdgeAgent.tenant_id == tenant_id,
            EdgeAgent.status == "online",
        )
    )
    if agent is None:
        raise ApplicationError(code="AIOPS_4201", message="Agent 不在线", status_code=409)
    return AgentExecutionTarget(id=agent.id, capabilities=dict(agent.capabilities))


def enqueue_automation_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    agent_id: UUID,
    automation_job_id: UUID,
    action_id: str,
    parameters: dict[str, Any],
    risk_level: str,
    created_by: UUID,
    timeout_seconds: int,
) -> None:
    task = AgentTask(
        tenant_id=tenant_id,
        project_id=project_id,
        asset_id=asset_id,
        agent_id=agent_id,
        automation_job_id=automation_job_id,
        action_id=action_id,
        parameters=parameters,
        risk_level=risk_level,
        status="queued",
        idempotency_key=f"automation-job:{automation_job_id}",
        created_by=created_by,
        expires_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
    )
    session.add(task)
