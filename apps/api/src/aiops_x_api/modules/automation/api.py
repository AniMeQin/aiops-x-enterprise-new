import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.agent_control.contracts import (
    enqueue_automation_task,
    require_online_agent_for_asset,
)
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.automation.infrastructure.models import (
    ApprovalDecision,
    ApprovalRequest,
    AutomationJob,
    Runbook,
    RunbookVersion,
)
from aiops_x_api.modules.automation.schemas import (
    ApprovalDecisionCreate,
    ApprovalPage,
    ApprovalResponse,
    AutomationJobCreate,
    AutomationJobPage,
    AutomationJobResponse,
    BuiltinRunbookCreate,
    RunbookPage,
    RunbookResponse,
    RunbookVersionResponse,
)
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.operations.contracts import (
    append_automation_timeline,
    maintenance_window_allows,
    require_automation_event,
)
from aiops_x_api.modules.tenant.application import require_project_scope

router = APIRouter(tags=["automation"])
RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}


@router.post("/runbooks/builtins", response_model=RunbookResponse, status_code=201)
async def ensure_builtin_runbook(
    payload: BuiltinRunbookCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("runbook:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunbookResponse:
    ensure_project_scope(principal, payload.project_id)
    async with session.begin():
        project = await require_project_scope(
            session, tenant_id=principal.tenant_id, project_id=payload.project_id
        )
        runbook = await session.scalar(
            select(Runbook).where(
                Runbook.tenant_id == principal.tenant_id,
                Runbook.project_id == project.id,
                Runbook.slug == "linux-disk-readonly-inspection",
            )
        )
        created = runbook is None
        if runbook is None:
            definition = _disk_runbook_definition()
            runbook = Runbook(
                tenant_id=principal.tenant_id,
                project_id=project.id,
                slug="linux-disk-readonly-inspection",
                name="Linux 磁盘只读巡检",
                description="通过注册 Action 读取指定挂载点容量，不执行任意 Shell，不修改设备。",
                status="published",
                current_version=1,
                created_by=principal.user_id,
            )
            session.add(runbook)
            await session.flush()
            version = RunbookVersion(
                runbook_id=runbook.id,
                version=1,
                created_by=principal.user_id,
                checksum=_definition_checksum(definition),
                **definition,
            )
            session.add(version)
            await session.flush()
            await append_audit(
                session,
                request,
                action="runbook.published",
                resource_type="runbook",
                outcome="success",
                principal=principal,
                project_id=project.id,
                resource_id=str(runbook.id),
                metadata={"slug": runbook.slug, "version": 1, "checksum": version.checksum},
            )
        versions = await _versions_for_runbook(session, runbook.id)
    response = _runbook_response(runbook, versions)
    if not created:
        return response
    return response


@router.get("/runbooks", response_model=RunbookPage)
async def list_runbooks(
    principal: Annotated[Principal, Depends(require_permission("runbook:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> RunbookPage:
    filters = [Runbook.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Runbook.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(Runbook.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(Runbook).where(*filters))
    runbooks = (
        await session.scalars(
            select(Runbook)
            .where(*filters)
            .order_by(Runbook.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        _runbook_response(runbook, await _versions_for_runbook(session, runbook.id))
        for runbook in runbooks
    ]
    return RunbookPage(items=items, page=page, page_size=page_size, total=total or 0)


@router.get("/runbooks/{runbook_id}", response_model=RunbookResponse)
async def get_runbook(
    runbook_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("runbook:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunbookResponse:
    runbook = await session.scalar(
        select(Runbook).where(Runbook.id == runbook_id, Runbook.tenant_id == principal.tenant_id)
    )
    if runbook is None:
        raise ApplicationError(code="AIOPS_6004", message="Runbook 不存在", status_code=404)
    ensure_project_scope(principal, runbook.project_id)
    return _runbook_response(runbook, await _versions_for_runbook(session, runbook.id))


@router.post("/automation/jobs", response_model=AutomationJobResponse, status_code=201)
async def create_automation_job(
    payload: AutomationJobCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("job:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)],
) -> AutomationJobResponse:
    now = datetime.now(UTC)
    async with session.begin():
        duplicate = await session.scalar(
            select(AutomationJob).where(
                AutomationJob.tenant_id == principal.tenant_id,
                AutomationJob.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return AutomationJobResponse.model_validate(duplicate)
        runbook = await session.scalar(
            select(Runbook).where(
                Runbook.id == payload.runbook_id,
                Runbook.tenant_id == principal.tenant_id,
                Runbook.status == "published",
            )
        )
        if runbook is None:
            raise ApplicationError(
                code="AIOPS_6004", message="Runbook 不存在或未发布", status_code=404
            )
        ensure_project_scope(principal, runbook.project_id)
        if runbook.current_version != payload.runbook_version:
            raise ApplicationError(
                code="AIOPS_6005", message="Runbook 版本已变更，请刷新后重试", status_code=409
            )
        version = await session.scalar(
            select(RunbookVersion).where(
                RunbookVersion.runbook_id == runbook.id,
                RunbookVersion.version == payload.runbook_version,
            )
        )
        if version is None:
            raise ApplicationError(code="AIOPS_6006", message="Runbook 版本不存在", status_code=404)
        if version.risk_level == "R4":
            raise ApplicationError(
                code="AIOPS_6104", message="R4 破坏性任务默认禁止", status_code=403
            )
        _require_all_permissions(principal, version.required_permissions)
        inputs = _validate_inputs(version.input_schema, payload.inputs)
        asset = await get_asset_for_scope(
            session, tenant_id=principal.tenant_id, asset_id=payload.asset_id
        )
        if asset.project_id != runbook.project_id:
            raise ApplicationError(
                code="AIOPS_3104", message="资产不存在或超出 Runbook 项目范围", status_code=404
            )
        if asset.asset_type not in version.asset_types:
            raise ApplicationError(
                code="AIOPS_6101", message="Runbook 不适用于该资产类型", status_code=409
            )
        agent = await require_online_agent_for_asset(
            session, tenant_id=principal.tenant_id, asset_id=asset.id
        )
        if version.action_id not in agent.capabilities.get("actions", []):
            raise ApplicationError(
                code="AIOPS_4202", message="Agent 未上报该动作能力", status_code=409
            )
        event = await require_automation_event(
            session,
            tenant_id=principal.tenant_id,
            project_id=runbook.project_id,
            event_id=payload.event_id,
            asset_id=asset.id,
        )
        maintenance_ok = await maintenance_window_allows(
            session,
            tenant_id=asset.tenant_id,
            project_id=asset.project_id,
            asset_id=asset.id,
            required=version.maintenance_window_required,
            now=now,
        )
        if not maintenance_ok:
            raise ApplicationError(
                code="AIOPS_6102", message="当前不在有效维护窗口内", status_code=409
            )
        approval_required = RISK_ORDER[version.risk_level] >= RISK_ORDER["R2"]
        job = AutomationJob(
            job_id=_human_id("JOB"),
            tenant_id=principal.tenant_id,
            project_id=runbook.project_id,
            asset_id=asset.id,
            agent_id=agent.id,
            event_id=event.id if event is not None else None,
            runbook_id=runbook.id,
            runbook_version_id=version.id,
            runbook_version=version.version,
            action_id=version.action_id,
            risk_level=version.risk_level,
            status="awaiting_approval" if approval_required else "queued",
            approval_status="pending" if approval_required else "not_required",
            inputs=inputs,
            policy_snapshot={
                "runbook_checksum": version.checksum,
                "runbook_status": runbook.status,
                "asset_type": asset.asset_type,
                "asset_gxp_classification": asset.gxp_classification,
                "agent_capability_verified": True,
                "permission_verified": True,
                "maintenance_window_required": version.maintenance_window_required,
                "maintenance_window_verified": maintenance_ok,
                "approval_required": approval_required,
            },
            idempotency_key=idempotency_key,
            requested_by=principal.user_id,
        )
        session.add(job)
        await session.flush()
        if approval_required:
            session.add(
                ApprovalRequest(
                    approval_id=_human_id("APR"),
                    tenant_id=job.tenant_id,
                    project_id=job.project_id,
                    job_id=job.id,
                    risk_level=job.risk_level,
                    required_approvals=2 if job.risk_level == "R4" else 1,
                    requester_id=principal.user_id,
                    expires_at=now + timedelta(hours=24),
                )
            )
        else:
            enqueue_automation_task(
                session,
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                asset_id=job.asset_id,
                agent_id=job.agent_id,
                automation_job_id=job.id,
                action_id=job.action_id,
                parameters=job.inputs,
                risk_level=job.risk_level,
                created_by=job.requested_by,
                timeout_seconds=version.timeout_seconds,
            )
        if event is not None:
            append_automation_timeline(
                session,
                event=event,
                job_id=job.id,
                job_number=job.job_id,
                runbook_id=job.runbook_id,
                runbook_version=job.runbook_version,
                action_id=job.action_id,
                risk_level=job.risk_level,
                status="queued",
                title="已发起只读巡检 Runbook",
                occurred_at=now,
            )
        await append_audit(
            session,
            request,
            action="automation.job.requested",
            resource_type="automation_job",
            outcome="success",
            principal=principal,
            project_id=job.project_id,
            resource_id=str(job.id),
            metadata={
                "job_id": job.job_id,
                "runbook_id": str(runbook.id),
                "runbook_version": version.version,
                "risk_level": version.risk_level,
                "event_id": str(job.event_id) if job.event_id else None,
            },
        )
    return AutomationJobResponse.model_validate(job)


@router.get("/automation/jobs", response_model=AutomationJobPage)
async def list_automation_jobs(
    principal: Annotated[Principal, Depends(require_permission("job:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    event_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
) -> AutomationJobPage:
    filters = [AutomationJob.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(AutomationJob.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(AutomationJob.project_id == project_id)
    if event_id is not None:
        filters.append(AutomationJob.event_id == event_id)
    if status:
        filters.append(AutomationJob.status == status)
    total = await session.scalar(select(func.count()).select_from(AutomationJob).where(*filters))
    jobs = (
        await session.scalars(
            select(AutomationJob)
            .where(*filters)
            .order_by(AutomationJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AutomationJobPage(
        items=[AutomationJobResponse.model_validate(item) for item in jobs],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.get("/automation/jobs/{job_id}", response_model=AutomationJobResponse)
async def get_automation_job(
    job_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("job:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AutomationJobResponse:
    job = await session.scalar(
        select(AutomationJob).where(
            AutomationJob.id == job_id, AutomationJob.tenant_id == principal.tenant_id
        )
    )
    if job is not None:
        ensure_project_scope(principal, job.project_id)
    if job is None:
        raise ApplicationError(code="AIOPS_6204", message="自动化任务不存在", status_code=404)
    return AutomationJobResponse.model_validate(job)


@router.get("/approvals", response_model=ApprovalPage)
async def list_approvals(
    principal: Annotated[Principal, Depends(require_permission("approval:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> ApprovalPage:
    filters = [ApprovalRequest.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(ApprovalRequest.project_id.in_(allowed_project_ids))
    if status:
        filters.append(ApprovalRequest.status == status)
    total = await session.scalar(select(func.count()).select_from(ApprovalRequest).where(*filters))
    approvals = (
        await session.scalars(
            select(ApprovalRequest)
            .where(*filters)
            .order_by(ApprovalRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        _approval_response(
            item,
            list(
                (
                    await session.scalars(
                        select(ApprovalDecision)
                        .where(ApprovalDecision.approval_request_id == item.id)
                        .order_by(ApprovalDecision.decided_at)
                    )
                ).all()
            ),
        )
        for item in approvals
    ]
    return ApprovalPage(items=items, page=page, page_size=page_size, total=total or 0)


@router.post("/approvals/{approval_id}/decisions", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecisionCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("approval:decide"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApprovalResponse:
    now = datetime.now(UTC)
    async with session.begin():
        approval = await session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if approval is None:
            raise ApplicationError(code="AIOPS_6304", message="审批单不存在", status_code=404)
        ensure_project_scope(principal, approval.project_id)
        if approval.status != "pending" or _as_utc(approval.expires_at) <= now:
            raise ApplicationError(code="AIOPS_6301", message="审批单已结束或过期", status_code=409)
        if approval.requester_id == principal.user_id:
            raise ApplicationError(
                code="AIOPS_6302", message="申请人不能审批自己的任务", status_code=403
            )
        existing = await session.scalar(
            select(ApprovalDecision).where(
                ApprovalDecision.approval_request_id == approval.id,
                ApprovalDecision.approver_id == principal.user_id,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_6303", message="您已经审批过该任务", status_code=409)
        decision = ApprovalDecision(
            approval_request_id=approval.id,
            approver_id=principal.user_id,
            decision=payload.decision,
            comment=payload.comment.strip(),
        )
        session.add(decision)
        await session.flush()
        job = await session.scalar(
            select(AutomationJob).where(AutomationJob.id == approval.job_id).with_for_update()
        )
        if job is None:
            raise ApplicationError(code="AIOPS_6204", message="自动化任务不存在", status_code=404)
        if payload.decision == "rejected":
            approval.status = "rejected"
            approval.resolved_at = now
            job.status = "rejected"
            job.approval_status = "rejected"
        else:
            approved_count = await session.scalar(
                select(func.count())
                .select_from(ApprovalDecision)
                .where(
                    ApprovalDecision.approval_request_id == approval.id,
                    ApprovalDecision.decision == "approved",
                )
            )
            if (approved_count or 0) >= approval.required_approvals:
                approval.status = "approved"
                approval.resolved_at = now
                job.status = "queued"
                job.approval_status = "approved"
                version = await session.scalar(
                    select(RunbookVersion).where(RunbookVersion.id == job.runbook_version_id)
                )
                if version is None:
                    raise ApplicationError(
                        code="AIOPS_6006", message="Runbook 版本不存在", status_code=404
                    )
                enqueue_automation_task(
                    session,
                    tenant_id=job.tenant_id,
                    project_id=job.project_id,
                    asset_id=job.asset_id,
                    agent_id=job.agent_id,
                    automation_job_id=job.id,
                    action_id=job.action_id,
                    parameters=job.inputs,
                    risk_level=job.risk_level,
                    created_by=job.requested_by,
                    timeout_seconds=version.timeout_seconds,
                )
        await append_audit(
            session,
            request,
            action=f"approval.{payload.decision}",
            resource_type="approval_request",
            outcome="success",
            principal=principal,
            project_id=approval.project_id,
            resource_id=str(approval.id),
            metadata={"job_id": str(job.id), "risk_level": approval.risk_level},
        )
        decisions = list(
            (
                await session.scalars(
                    select(ApprovalDecision)
                    .where(ApprovalDecision.approval_request_id == approval.id)
                    .order_by(ApprovalDecision.decided_at)
                )
            ).all()
        )
    return _approval_response(approval, decisions)


def _disk_runbook_definition() -> dict[str, Any]:
    return {
        "action_id": "system.disk_usage",
        "asset_types": ["linux"],
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^/"},
                    "minItems": 1,
                    "maxItems": 8,
                    "default": ["/"],
                }
            },
            "required": ["paths"],
        },
        "risk_level": "R0",
        "required_permissions": ["job:write", "asset:read"],
        "timeout_seconds": 60,
        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
        "idempotent": True,
        "pre_checks": [
            {"check": "agent_online"},
            {"check": "capability_registered", "action_id": "system.disk_usage"},
        ],
        "execution_steps": [{"step": 1, "action_id": "system.disk_usage", "mode": "read_only"}],
        "post_checks": [{"check": "structured_filesystem_output"}],
        "success_conditions": ["agent_result_status == succeeded"],
        "failure_conditions": ["agent_timeout", "signature_invalid", "action_failed"],
        "rollback_steps": [],
        "approval_policy": {"required": False, "reason": "R0_read_only"},
        "maintenance_window_required": False,
        "output_redaction_rules": ["credential", "token", "password", "private_key"],
    }


def _definition_checksum(definition: dict[str, Any]) -> str:
    value = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


async def _versions_for_runbook(session: AsyncSession, runbook_id: UUID) -> list[RunbookVersion]:
    return list(
        (
            await session.scalars(
                select(RunbookVersion)
                .where(RunbookVersion.runbook_id == runbook_id)
                .order_by(RunbookVersion.version.desc())
            )
        ).all()
    )


def _runbook_response(runbook: Runbook, versions: list[RunbookVersion]) -> RunbookResponse:
    return RunbookResponse(
        **RunbookResponse.model_validate(runbook).model_dump(exclude={"versions"}),
        versions=[RunbookVersionResponse.model_validate(item) for item in versions],
    )


def _approval_response(
    approval: ApprovalRequest, decisions: list[ApprovalDecision]
) -> ApprovalResponse:
    return ApprovalResponse(
        **ApprovalResponse.model_validate(approval).model_dump(exclude={"decisions"}),
        decisions=decisions,
    )


def _validate_inputs(schema: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ApplicationError(
            code="AIOPS_6007", message="Runbook 输入 Schema 无效", status_code=500
        )
    if schema.get("additionalProperties") is False and set(inputs) - set(properties):
        raise ApplicationError(
            code="AIOPS_6103", message="Runbook 输入包含未定义字段", status_code=422
        )
    if any(name not in inputs for name in required):
        raise ApplicationError(
            code="AIOPS_6103", message="Runbook 输入缺少必填字段", status_code=422
        )
    paths = inputs.get("paths")
    if paths is not None:
        if not isinstance(paths, list) or not 1 <= len(paths) <= 8:
            raise ApplicationError(
                code="AIOPS_6103", message="paths 必须包含 1 至 8 个路径", status_code=422
            )
        if any(
            not isinstance(path, str) or not path.startswith("/") or len(path) > 255
            for path in paths
        ):
            raise ApplicationError(
                code="AIOPS_6103", message="paths 必须是绝对路径", status_code=422
            )
    return inputs


def _require_all_permissions(principal: Principal, permissions: list[str]) -> None:
    if "*" in principal.permissions:
        return
    missing = sorted(set(permissions) - principal.permissions)
    if missing:
        raise ApplicationError(
            code="AIOPS_2002",
            message="当前账号缺少 Runbook 所需权限",
            status_code=403,
            details={"missing_permissions": missing},
        )


def _human_id(prefix: str) -> str:
    now = datetime.now(UTC)
    return f"{prefix}-{now:%Y%m%d}-{uuid4().hex[:8].upper()}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
