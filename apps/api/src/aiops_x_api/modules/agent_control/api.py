from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.core.observability import AGENTS_ONLINE, AUTOMATION_DURATION, AUTOMATION_JOBS
from aiops_x_api.modules.agent_control.infrastructure.models import (
    AgentRegistrationToken,
    AgentTask,
    EdgeAgent,
)
from aiops_x_api.modules.agent_control.pki import (
    canonical_task_payload,
    csr_fingerprint,
    issue_agent_certificate,
    sign_task,
    task_signing_certificate_pem,
)
from aiops_x_api.modules.agent_control.schemas import (
    AgentCertificateRenewalRequest,
    AgentCertificateRenewalResponse,
    AgentDisableRequest,
    AgentEnrollmentRequest,
    AgentEnrollmentResponse,
    AgentHeartbeatRequest,
    AgentPage,
    AgentResponse,
    AgentTaskCreate,
    AgentTaskEnvelope,
    AgentTaskPage,
    AgentTaskResponse,
    AgentTaskResult,
    RegistrationTokenCreate,
    RegistrationTokenResponse,
)
from aiops_x_api.modules.agent_control.security import AgentPrincipal, get_current_agent
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.automation.infrastructure.models import AutomationJob
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    generate_opaque_token,
    require_permission,
    scoped_project_ids,
    token_hash,
)
from aiops_x_api.modules.operations.infrastructure.models import (
    EventTimelineEntry,
    OperationsEvent,
)

router = APIRouter(prefix="/agents", tags=["agent-control"])
ENROLLMENT_ACTIONS = {"system.disk_usage"}


@router.post("/registration-tokens", response_model=RegistrationTokenResponse, status_code=201)
async def create_registration_token(
    payload: RegistrationTokenCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("agent:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RegistrationTokenResponse:
    ensure_project_scope(principal, payload.project_id)
    now = datetime.now(UTC)
    raw_token = "axt_" + generate_opaque_token()
    async with session.begin():
        asset = await _asset_in_tenant(session, principal.tenant_id, payload.asset_id)
        if asset.project_id != payload.project_id:
            raise ApplicationError(
                code="AIOPS_4101", message="Agent 注册范围与资产项目不匹配", status_code=409
            )
        existing_agent = await session.scalar(
            select(EdgeAgent.id).where(
                EdgeAgent.tenant_id == principal.tenant_id,
                EdgeAgent.asset_id == asset.id,
                EdgeAgent.status != "disabled",
            )
        )
        if existing_agent is not None:
            raise ApplicationError(
                code="AIOPS_4102", message="资产已绑定有效 Agent", status_code=409
            )
        registration = AgentRegistrationToken(
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            asset_id=payload.asset_id,
            token_hash=token_hash(raw_token),
            token_prefix=raw_token[:12],
            expires_at=now + timedelta(seconds=payload.expires_in_seconds),
            created_by=principal.user_id,
        )
        session.add(registration)
        await session.flush()
        await append_audit(
            session,
            request,
            action="agent.registration_token.created",
            resource_type="agent_registration_token",
            outcome="success",
            principal=principal,
            project_id=payload.project_id,
            resource_id=str(registration.id),
            metadata={
                "asset_id": str(payload.asset_id),
                "expires_at": registration.expires_at.isoformat(),
            },
        )
    return RegistrationTokenResponse(
        id=registration.id,
        token=raw_token,
        token_prefix=registration.token_prefix,
        project_id=registration.project_id,
        asset_id=registration.asset_id,
        expires_at=registration.expires_at,
    )


@router.post("/enroll", response_model=AgentEnrollmentResponse, status_code=201)
async def enroll_agent(
    payload: AgentEnrollmentRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentEnrollmentResponse:
    now = datetime.now(UTC)
    registration_hash = token_hash(payload.registration_token)
    async with session.begin():
        registration = await session.scalar(
            select(AgentRegistrationToken)
            .where(AgentRegistrationToken.token_hash == registration_hash)
            .with_for_update()
        )
        if (
            registration is None
            or registration.used_at is not None
            or _as_utc(registration.expires_at) <= now
        ):
            raise ApplicationError(
                code="AIOPS_4103", message="Agent 注册令牌无效、已使用或已过期", status_code=401
            )
        asset = await _asset_in_tenant(session, registration.tenant_id, registration.asset_id)
        agent_id = uuid4()
        (
            certificate_pem,
            ca_certificate_pem,
            certificate_serial,
            certificate_not_after,
            certificate_fingerprint,
        ) = issue_agent_certificate(payload.csr_pem, agent_id)
        capabilities = _validated_capabilities(payload.capabilities)
        agent = EdgeAgent(
            id=agent_id,
            tenant_id=registration.tenant_id,
            project_id=registration.project_id,
            asset_id=registration.asset_id,
            name=payload.name.strip(),
            hostname=payload.hostname.strip(),
            platform=payload.platform.strip(),
            architecture=payload.architecture.strip(),
            version=payload.version.strip(),
            capabilities=capabilities,
            certificate_serial=certificate_serial,
            certificate_fingerprint=certificate_fingerprint,
            certificate_not_after=certificate_not_after,
        )
        session.add(agent)
        registration.used_at = now
        asset.agent_status = "registered"
        asset.hostname = payload.hostname.strip()
        await append_audit(
            session,
            request,
            action="agent.registered",
            resource_type="agent",
            outcome="success",
            actor_type="agent",
            actor_id=str(agent.id),
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            resource_id=str(agent.id),
            metadata={
                "asset_id": str(agent.asset_id),
                "platform": agent.platform,
                "architecture": agent.architecture,
                "token_id": str(registration.id),
            },
        )
    return AgentEnrollmentResponse(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        project_id=agent.project_id,
        asset_id=agent.asset_id,
        certificate_pem=certificate_pem,
        ca_certificate_pem=ca_certificate_pem,
        task_signing_certificate_pem=task_signing_certificate_pem(),
        certificate_not_after=certificate_not_after,
    )


@router.post(
    "/{agent_id}/certificate/renew",
    response_model=AgentCertificateRenewalResponse,
)
async def renew_agent_certificate(
    agent_id: UUID,
    payload: AgentCertificateRenewalRequest,
    request: Request,
    authenticated_agent: Annotated[AgentPrincipal, Depends(get_current_agent)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentCertificateRenewalResponse:
    _require_agent_scope(authenticated_agent, agent_id, allow_previous_certificate=True)
    now = datetime.now(UTC)
    renewal_window = timedelta(hours=get_settings().agent_certificate_renewal_window_hours)
    async with session.begin():
        agent = await session.scalar(
            select(EdgeAgent).where(EdgeAgent.id == agent_id).with_for_update()
        )
        if agent is None or agent.status == "disabled":
            raise ApplicationError(
                code="AIOPS_4001", message="Agent 身份凭据无效或已过期", status_code=401
            )
        renewing_current = agent.certificate_serial == authenticated_agent.certificate_serial
        retrying_previous = (
            agent.previous_certificate_serial == authenticated_agent.certificate_serial
        )
        if not renewing_current and not retrying_previous:
            raise ApplicationError(
                code="AIOPS_4001", message="Agent 身份凭据无效或已过期", status_code=401
            )
        if renewing_current and _as_utc(agent.certificate_not_after) > now + renewal_window:
            raise ApplicationError(
                code="AIOPS_4105", message="Agent 证书尚未进入续期窗口", status_code=409
            )
        renewal_csr_fingerprint = csr_fingerprint(payload.csr_pem)
        if retrying_previous and renewal_csr_fingerprint != agent.last_renewal_csr_fingerprint:
            raise ApplicationError(
                code="AIOPS_4106", message="Agent 续期请求与待恢复身份不匹配", status_code=409
            )

        (
            certificate_pem,
            ca_certificate_pem,
            certificate_serial,
            certificate_not_after,
            certificate_fingerprint,
        ) = issue_agent_certificate(payload.csr_pem, agent.id)
        if renewing_current:
            agent.previous_certificate_serial = agent.certificate_serial
            agent.previous_certificate_fingerprint = agent.certificate_fingerprint
            agent.previous_certificate_not_after = agent.certificate_not_after
            agent.last_renewal_csr_fingerprint = renewal_csr_fingerprint
        agent.certificate_serial = certificate_serial
        agent.certificate_fingerprint = certificate_fingerprint
        agent.certificate_not_after = certificate_not_after
        await append_audit(
            session,
            request,
            action="agent.certificate.renewed",
            resource_type="agent",
            outcome="success",
            actor_type="agent",
            actor_id=str(agent.id),
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            resource_id=str(agent.id),
            metadata={
                "certificate_not_after": certificate_not_after.isoformat(),
                "retry_via_previous_certificate": retrying_previous,
            },
        )
    return AgentCertificateRenewalResponse(
        agent_id=agent.id,
        certificate_pem=certificate_pem,
        ca_certificate_pem=ca_certificate_pem,
        task_signing_certificate_pem=task_signing_certificate_pem(),
        certificate_not_after=certificate_not_after,
    )


@router.get("", response_model=AgentPage)
async def list_agents(
    principal: Annotated[Principal, Depends(require_permission("agent:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> AgentPage:
    filters = [EdgeAgent.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(EdgeAgent.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(EdgeAgent.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(EdgeAgent).where(*filters))
    online = await session.scalar(
        select(func.count()).select_from(EdgeAgent).where(*filters, EdgeAgent.status == "online")
    )
    AGENTS_ONLINE.labels(str(principal.tenant_id)).set(online or 0)
    rows = (
        await session.scalars(
            select(EdgeAgent)
            .where(*filters)
            .order_by(EdgeAgent.registered_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AgentPage(
        items=[AgentResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/{agent_id}/disable", response_model=AgentResponse)
async def disable_agent(
    agent_id: UUID,
    payload: AgentDisableRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("agent:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentResponse:
    now = datetime.now(UTC)
    async with session.begin():
        agent = await session.scalar(
            select(EdgeAgent)
            .where(EdgeAgent.id == agent_id, EdgeAgent.tenant_id == principal.tenant_id)
            .with_for_update()
        )
        if agent is None:
            raise ApplicationError(code="AIOPS_4004", message="Agent 不存在", status_code=404)
        ensure_project_scope(principal, agent.project_id)
        if agent.status == "disabled":
            return AgentResponse.model_validate(agent)
        running_task = await session.scalar(
            select(AgentTask.id).where(
                AgentTask.agent_id == agent.id, AgentTask.status == "running"
            )
        )
        if running_task is not None:
            raise ApplicationError(
                code="AIOPS_4301",
                message="Agent 存在执行中的任务，不能停用",
                status_code=409,
            )
        queued_tasks = (
            await session.scalars(
                select(AgentTask).where(
                    AgentTask.agent_id == agent.id, AgentTask.status == "queued"
                )
            )
        ).all()
        for task in queued_tasks:
            task.status = "canceled"
            task.completed_at = now
            task.error_code = "AGENT_DISABLED"
            task.error_message = "Agent 已由管理员停用"
            if task.automation_job_id is not None:
                job = await session.scalar(
                    select(AutomationJob).where(AutomationJob.id == task.automation_job_id)
                )
                if job is not None and job.status == "queued":
                    job.status = "canceled"
                    job.completed_at = now
                    job.error_code = "AGENT_DISABLED"
                    job.error_message = "Agent 已由管理员停用"
        agent.status = "disabled"
        agent.health_status = "unknown"
        agent.disabled_at = now
        agent.disabled_by = principal.user_id
        agent.disable_reason = payload.reason.strip()
        asset = await _asset_in_tenant(session, principal.tenant_id, agent.asset_id)
        asset.agent_status = "not_installed"
        await append_audit(
            session,
            request,
            action="agent.disabled",
            resource_type="agent",
            outcome="success",
            principal=principal,
            project_id=agent.project_id,
            resource_id=str(agent.id),
            metadata={
                "asset_id": str(agent.asset_id),
                "reason": agent.disable_reason,
                "canceled_task_count": len(queued_tasks),
            },
        )
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/heartbeat", response_model=AgentResponse)
async def heartbeat(
    agent_id: UUID,
    payload: AgentHeartbeatRequest,
    request: Request,
    authenticated_agent: Annotated[AgentPrincipal, Depends(get_current_agent)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentResponse:
    _require_agent_scope(authenticated_agent, agent_id)
    now = datetime.now(UTC)
    async with session.begin():
        agent = await _agent_by_id(session, agent_id)
        agent.hostname = payload.hostname.strip()
        agent.platform = payload.platform.strip()
        agent.architecture = payload.architecture.strip()
        agent.version = payload.version.strip()
        agent.health_status = payload.health_status
        agent.capabilities = _validated_capabilities(payload.capabilities)
        agent.status = "online"
        agent.last_heartbeat_at = now
        asset = await _asset_in_tenant(session, agent.tenant_id, agent.asset_id)
        asset.agent_status = "online"
        asset.hostname = agent.hostname
        tenant_online = await session.scalar(
            select(func.count())
            .select_from(EdgeAgent)
            .where(
                EdgeAgent.tenant_id == agent.tenant_id,
                EdgeAgent.status == "online",
            )
        )
        AGENTS_ONLINE.labels(str(agent.tenant_id)).set(tenant_online or 0)
        await append_audit(
            session,
            request,
            action="agent.heartbeat.received",
            resource_type="agent",
            outcome="success",
            actor_type="agent",
            actor_id=str(agent.id),
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            resource_id=str(agent.id),
            metadata={"health_status": agent.health_status, "version": agent.version},
        )
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/tasks", response_model=AgentTaskResponse, status_code=201)
async def create_task(
    agent_id: UUID,
    payload: AgentTaskCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("job:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)],
) -> AgentTaskResponse:
    now = datetime.now(UTC)
    async with session.begin():
        duplicate = await session.scalar(
            select(AgentTask).where(
                AgentTask.tenant_id == principal.tenant_id,
                AgentTask.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return AgentTaskResponse.model_validate(duplicate)
        agent = await session.scalar(
            select(EdgeAgent).where(
                EdgeAgent.id == agent_id, EdgeAgent.tenant_id == principal.tenant_id
            )
        )
        if agent is None or agent.status != "online":
            raise ApplicationError(code="AIOPS_4201", message="Agent 不在线", status_code=409)
        ensure_project_scope(principal, agent.project_id)
        actions = agent.capabilities.get("actions", [])
        if payload.action_id not in actions:
            raise ApplicationError(
                code="AIOPS_4202", message="Agent 未上报该动作能力", status_code=409
            )
        task = AgentTask(
            tenant_id=agent.tenant_id,
            project_id=agent.project_id,
            asset_id=agent.asset_id,
            agent_id=agent.id,
            action_id=payload.action_id,
            parameters=payload.parameters,
            risk_level="R0",
            status="queued",
            idempotency_key=idempotency_key,
            created_by=principal.user_id,
            expires_at=now + timedelta(seconds=payload.expires_in_seconds),
        )
        session.add(task)
        await session.flush()
        await append_audit(
            session,
            request,
            action="agent.task.queued",
            resource_type="agent_task",
            outcome="success",
            principal=principal,
            project_id=task.project_id,
            resource_id=str(task.id),
            metadata={"agent_id": str(agent.id), "action_id": task.action_id, "risk_level": "R0"},
        )
    return AgentTaskResponse.model_validate(task)


@router.get("/{agent_id}/tasks/next", response_model=AgentTaskEnvelope | None)
async def next_task(
    agent_id: UUID,
    request: Request,
    authenticated_agent: Annotated[AgentPrincipal, Depends(get_current_agent)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentTaskEnvelope | None:
    _require_agent_scope(authenticated_agent, agent_id)
    now = datetime.now(UTC)
    async with session.begin():
        task = await session.scalar(
            select(AgentTask)
            .where(
                AgentTask.agent_id == agent_id,
                AgentTask.status == "queued",
                AgentTask.expires_at > now,
            )
            .order_by(AgentTask.created_at.asc())
            .with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        task.status = "running"
        task.started_at = now
        automation_job = None
        if task.automation_job_id is not None:
            automation_job = await session.scalar(
                select(AutomationJob)
                .where(AutomationJob.id == task.automation_job_id)
                .with_for_update()
            )
            if automation_job is None or automation_job.status != "queued":
                raise ApplicationError(
                    code="AIOPS_6205", message="自动化任务状态冲突", status_code=409
                )
            automation_job.status = "running"
            automation_job.started_at = now
        signing_payload = canonical_task_payload(
            {
                "action_id": task.action_id,
                "expires_at": _as_utc(task.expires_at).isoformat().replace("+00:00", "Z"),
                "parameters": task.parameters,
                "task_id": str(task.id),
            }
        )
        signature = sign_task(signing_payload)
        await append_audit(
            session,
            request,
            action="agent.task.dispatched",
            resource_type="agent_task",
            outcome="success",
            actor_type="agent",
            actor_id=str(authenticated_agent.agent_id),
            tenant_id=task.tenant_id,
            project_id=task.project_id,
            resource_id=str(task.id),
            metadata={"action_id": task.action_id},
        )
        if automation_job is not None:
            await append_audit(
                session,
                request,
                action="automation.job.dispatched",
                resource_type="automation_job",
                outcome="success",
                actor_type="agent",
                actor_id=str(authenticated_agent.agent_id),
                tenant_id=automation_job.tenant_id,
                project_id=automation_job.project_id,
                resource_id=str(automation_job.id),
                metadata={"job_id": automation_job.job_id, "agent_task_id": str(task.id)},
            )
    return AgentTaskEnvelope(task_id=task.id, signing_payload=signing_payload, signature=signature)


@router.post("/{agent_id}/tasks/{task_id}/result", response_model=AgentTaskResponse)
async def submit_task_result(
    agent_id: UUID,
    task_id: UUID,
    payload: AgentTaskResult,
    request: Request,
    authenticated_agent: Annotated[AgentPrincipal, Depends(get_current_agent)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentTaskResponse:
    _require_agent_scope(authenticated_agent, agent_id)
    async with session.begin():
        task = await session.scalar(
            select(AgentTask)
            .where(AgentTask.id == task_id, AgentTask.agent_id == agent_id)
            .with_for_update()
        )
        if task is None:
            raise ApplicationError(code="AIOPS_4204", message="Agent 任务不存在", status_code=404)
        if task.status in {"succeeded", "failed"}:
            return AgentTaskResponse.model_validate(task)
        if task.status != "running":
            raise ApplicationError(code="AIOPS_4205", message="Agent 任务状态冲突", status_code=409)
        task.status = payload.status
        task.duration_ms = payload.duration_ms
        task.sanitized_output = payload.sanitized_output
        task.error_code = payload.error_code
        task.error_message = payload.error_message
        task.completed_at = datetime.now(UTC)
        automation_job = None
        if task.automation_job_id is not None:
            automation_job = await session.scalar(
                select(AutomationJob)
                .where(AutomationJob.id == task.automation_job_id)
                .with_for_update()
            )
            if automation_job is None:
                raise ApplicationError(
                    code="AIOPS_6204", message="自动化任务不存在", status_code=409
                )
            automation_job.status = payload.status
            automation_job.started_at = task.started_at
            automation_job.completed_at = task.completed_at
            automation_job.duration_ms = payload.duration_ms
            automation_job.sanitized_output = payload.sanitized_output
            automation_job.error_code = payload.error_code
            automation_job.error_message = payload.error_message
            if automation_job.event_id is not None:
                event = await session.scalar(
                    select(OperationsEvent).where(OperationsEvent.id == automation_job.event_id)
                )
                if event is not None:
                    session.add(
                        EventTimelineEntry(
                            tenant_id=event.tenant_id,
                            project_id=event.project_id,
                            event_id=event.id,
                            occurred_at=task.completed_at,
                            category="automation",
                            title=(
                                "Runbook 执行成功"
                                if payload.status == "succeeded"
                                else "Runbook 执行失败"
                            ),
                            description=f"{automation_job.job_id} / {task.action_id}",
                            source_type="automation_job",
                            source_id=str(automation_job.id),
                            evidence_refs=[
                                {
                                    "type": "agent_task_result",
                                    "task_id": str(task.id),
                                    "duration_ms": payload.duration_ms,
                                    "sanitized_output": payload.sanitized_output,
                                }
                            ],
                            metadata_json={
                                "job_id": automation_job.job_id,
                                "status": payload.status,
                                "runbook_id": str(automation_job.runbook_id),
                                "runbook_version": automation_job.runbook_version,
                            },
                        )
                    )
        await append_audit(
            session,
            request,
            action="agent.task.completed",
            resource_type="agent_task",
            outcome="success" if payload.status == "succeeded" else "failure",
            actor_type="agent",
            actor_id=str(authenticated_agent.agent_id),
            tenant_id=task.tenant_id,
            project_id=task.project_id,
            resource_id=str(task.id),
            metadata={"action_id": task.action_id, "duration_ms": task.duration_ms},
        )
        if automation_job is not None:
            AUTOMATION_JOBS.labels(payload.status).inc()
            AUTOMATION_DURATION.observe(payload.duration_ms / 1000)
            await append_audit(
                session,
                request,
                action="automation.job.completed",
                resource_type="automation_job",
                outcome="success" if payload.status == "succeeded" else "failure",
                actor_type="agent",
                actor_id=str(authenticated_agent.agent_id),
                tenant_id=automation_job.tenant_id,
                project_id=automation_job.project_id,
                resource_id=str(automation_job.id),
                metadata={
                    "job_id": automation_job.job_id,
                    "event_id": (str(automation_job.event_id) if automation_job.event_id else None),
                    "runbook_version": automation_job.runbook_version,
                    "duration_ms": payload.duration_ms,
                },
            )
    return AgentTaskResponse.model_validate(task)


@router.get("/{agent_id}/tasks", response_model=AgentTaskPage)
async def list_agent_tasks(
    agent_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("job:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentTaskPage:
    agent = await session.scalar(
        select(EdgeAgent).where(
            EdgeAgent.id == agent_id, EdgeAgent.tenant_id == principal.tenant_id
        )
    )
    if agent is None:
        raise ApplicationError(code="AIOPS_4004", message="Agent 不存在", status_code=404)
    ensure_project_scope(principal, agent.project_id)
    filters = [AgentTask.tenant_id == principal.tenant_id, AgentTask.agent_id == agent_id]
    total = await session.scalar(select(func.count()).select_from(AgentTask).where(*filters))
    rows = (
        await session.scalars(
            select(AgentTask)
            .where(*filters)
            .order_by(AgentTask.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AgentTaskPage(
        items=[AgentTaskResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


async def _asset_in_tenant(session: AsyncSession, tenant_id: UUID, asset_id: UUID) -> Asset:
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id)
    )
    if asset is None:
        raise ApplicationError(code="AIOPS_3104", message="资产不存在", status_code=404)
    return asset


async def _agent_by_id(session: AsyncSession, agent_id: UUID) -> EdgeAgent:
    agent = await session.scalar(select(EdgeAgent).where(EdgeAgent.id == agent_id))
    if agent is None:
        raise ApplicationError(code="AIOPS_4004", message="Agent 不存在", status_code=404)
    return agent


def _validated_capabilities(value: dict[str, object]) -> dict[str, object]:
    actions = value.get("actions", [])
    if not isinstance(actions, list) or not set(actions) <= ENROLLMENT_ACTIONS:
        raise ApplicationError(code="AIOPS_4104", message="Agent 上报了未注册动作", status_code=422)
    return value


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_agent_scope(
    authenticated_agent: AgentPrincipal,
    agent_id: UUID,
    *,
    allow_previous_certificate: bool = False,
) -> None:
    if authenticated_agent.agent_id != agent_id:
        raise ApplicationError(code="AIOPS_4003", message="Agent 身份范围不匹配", status_code=403)
    if not allow_previous_certificate and not authenticated_agent.is_current_certificate:
        raise ApplicationError(
            code="AIOPS_4001", message="Agent 身份凭据无效或已过期", status_code=401
        )
