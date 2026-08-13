from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.automation.contracts import require_automation_job_ref
from aiops_x_api.modules.change.application import (
    get_change_in_scope,
    human_change_number,
    required_approval_count,
    validate_change_links,
    validate_status_transition,
)
from aiops_x_api.modules.change.infrastructure.models import (
    ChangeApprovalDecision,
    ChangeRequest,
    ChangeTimelineEntry,
)
from aiops_x_api.modules.change.schemas import (
    ApprovalDecisionCreate,
    ApprovalDecisionResponse,
    ChangeCreate,
    ChangeDetail,
    ChangePage,
    ChangeResponse,
    ChangeStatusUpdate,
    ChangeTimelineResponse,
    ChangeUpdate,
)
from aiops_x_api.modules.evidence.application import require_evidence_refs
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/changes", tags=["changes"])


@router.get("", response_model=ChangePage)
async def list_changes(
    principal: Annotated[Principal, Depends(require_permission("change:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    risk_level: Annotated[str | None, Query(max_length=8)] = None,
) -> ChangePage:
    filters = [ChangeRequest.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(ChangeRequest.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(ChangeRequest.project_id == project_id)
    if status:
        filters.append(ChangeRequest.status == status)
    if risk_level:
        filters.append(ChangeRequest.risk_level == risk_level)
    total = await session.scalar(select(func.count()).select_from(ChangeRequest).where(*filters))
    rows = (
        await session.scalars(
            select(ChangeRequest)
            .where(*filters)
            .order_by(ChangeRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ChangePage(
        items=[ChangeResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("", response_model=ChangeResponse, status_code=201)
async def create_change(
    payload: ChangeCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("change:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeResponse:
    ensure_project_scope(principal, payload.project_id)
    approvals = required_approval_count(payload.risk_level, payload.gxp_impact)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        await require_evidence_refs(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            evidence_ids=payload.evidence_ids,
        )
        linked_assets = await validate_change_links(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            asset_ids=payload.affected_asset_ids,
            incident_ids=payload.incident_ids,
        )
        for asset in linked_assets:
            ensure_asset_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        change = ChangeRequest(
            change_number=human_change_number(),
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            change_type=payload.change_type,
            risk_level=payload.risk_level,
            status="draft",
            gxp_impact=payload.gxp_impact,
            affected_asset_ids=_uuid_strings(payload.affected_asset_ids),
            incident_ids=_uuid_strings(payload.incident_ids),
            evidence_ids=_uuid_strings(payload.evidence_ids),
            implementation_plan=payload.implementation_plan,
            precheck_plan=payload.precheck_plan,
            validation_plan=payload.validation_plan,
            success_criteria=payload.success_criteria,
            rollback_plan=payload.rollback_plan,
            impact_analysis=payload.impact_analysis,
            approval_policy_snapshot={
                "risk_level": payload.risk_level,
                "gxp_impact": payload.gxp_impact,
                "required_approvals": approvals,
                "requester_cannot_approve": approvals > 0,
                "r4_enabled": False,
            },
            required_approvals=approvals,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            configuration_backup_ref=payload.configuration_backup_ref,
            requested_by=principal.user_id,
        )
        session.add(change)
        await session.flush()
        _append_timeline(change, principal.user_id, "draft", "变更草稿已创建")
        await append_audit(
            session,
            request,
            action="change.created",
            resource_type="change",
            outcome="success",
            principal=principal,
            project_id=change.project_id,
            resource_id=str(change.id),
            metadata={"change_number": change.change_number, "risk_level": change.risk_level},
        )
    return ChangeResponse.model_validate(change)


@router.get("/{change_id}", response_model=ChangeDetail)
async def get_change(
    change_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("change:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeDetail:
    change = await get_change_in_scope(session, tenant_id=principal.tenant_id, change_id=change_id)
    ensure_project_scope(principal, change.project_id)
    approvals = (
        await session.scalars(
            select(ChangeApprovalDecision)
            .where(ChangeApprovalDecision.change_id == change.id)
            .order_by(ChangeApprovalDecision.decided_at)
        )
    ).all()
    timeline = (
        await session.scalars(
            select(ChangeTimelineEntry)
            .where(ChangeTimelineEntry.change_id == change.id)
            .order_by(ChangeTimelineEntry.occurred_at, ChangeTimelineEntry.created_at)
        )
    ).all()
    return ChangeDetail(
        **ChangeResponse.model_validate(change).model_dump(),
        approvals=[ApprovalDecisionResponse.model_validate(row) for row in approvals],
        timeline=[ChangeTimelineResponse.model_validate(row) for row in timeline],
    )


@router.patch("/{change_id}", response_model=ChangeResponse)
async def update_change(
    change_id: UUID,
    payload: ChangeUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("change:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeResponse:
    async with session.begin():
        change = await get_change_in_scope(
            session, tenant_id=principal.tenant_id, change_id=change_id, for_update=True
        )
        ensure_project_scope(principal, change.project_id)
        if change.status != "draft":
            raise ApplicationError(
                code="AIOPS_8210", message="只有草稿状态的变更可以编辑", status_code=409
            )
        changes = payload.model_dump(exclude_unset=True)
        if payload.evidence_ids is not None:
            await require_evidence_refs(
                session,
                tenant_id=principal.tenant_id,
                project_id=change.project_id,
                evidence_ids=payload.evidence_ids,
            )
        linked_assets = await validate_change_links(
            session,
            tenant_id=principal.tenant_id,
            project_id=change.project_id,
            asset_ids=(
                payload.affected_asset_ids
                if payload.affected_asset_ids is not None
                else _uuid_values(change.affected_asset_ids)
            ),
            incident_ids=(
                payload.incident_ids
                if payload.incident_ids is not None
                else _uuid_values(change.incident_ids)
            ),
        )
        for asset in linked_assets:
            ensure_asset_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        for field, value in changes.items():
            if (
                field in {"affected_asset_ids", "incident_ids", "evidence_ids"}
                and value is not None
            ):
                value = _uuid_strings(value)
            setattr(change, field, value)
        if (
            change.scheduled_start
            and change.scheduled_end
            and change.scheduled_end <= change.scheduled_start
        ):
            raise ApplicationError(
                code="AIOPS_8211", message="计划结束时间必须晚于开始时间", status_code=422
            )
        await append_audit(
            session,
            request,
            action="change.updated",
            resource_type="change",
            outcome="success",
            principal=principal,
            project_id=change.project_id,
            resource_id=str(change.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(change)
    return ChangeResponse.model_validate(change)


@router.post("/{change_id}/submit", response_model=ChangeResponse)
async def submit_change(
    change_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("change:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeResponse:
    now = datetime.now(UTC)
    async with session.begin():
        change = await get_change_in_scope(
            session, tenant_id=principal.tenant_id, change_id=change_id, for_update=True
        )
        ensure_project_scope(principal, change.project_id)
        target = "pending_approval" if change.required_approvals else "approved"
        validate_status_transition(change.status, target)
        if change.risk_level in {"R2", "R3"} or change.gxp_impact:
            if not all(
                (
                    change.precheck_plan,
                    change.implementation_plan,
                    change.validation_plan,
                    change.success_criteria,
                    change.rollback_plan,
                )
            ):
                raise ApplicationError(
                    code="AIOPS_8212",
                    message="受控变更提交前必须补齐前置检查、验证和回滚方案",
                    status_code=422,
                )
        change.status = target
        change.submitted_at = now
        if target == "approved":
            change.approved_at = now
        _append_timeline(change, principal.user_id, target, "变更已提交")
        await append_audit(
            session,
            request,
            action="change.submitted",
            resource_type="change",
            outcome="success",
            principal=principal,
            project_id=change.project_id,
            resource_id=str(change.id),
            metadata={"required_approvals": change.required_approvals},
        )
        await session.flush()
        await session.refresh(change)
    return ChangeResponse.model_validate(change)


@router.post("/{change_id}/decisions", response_model=ChangeResponse)
async def decide_change(
    change_id: UUID,
    payload: ApprovalDecisionCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("change:approve"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeResponse:
    now = datetime.now(UTC)
    async with session.begin():
        change = await get_change_in_scope(
            session, tenant_id=principal.tenant_id, change_id=change_id, for_update=True
        )
        ensure_project_scope(principal, change.project_id)
        if change.status != "pending_approval":
            raise ApplicationError(
                code="AIOPS_8213", message="当前变更不在待审批状态", status_code=409
            )
        if change.requested_by == principal.user_id:
            raise ApplicationError(
                code="AIOPS_8214", message="变更申请人不能审批自己的变更", status_code=403
            )
        existing = await session.scalar(
            select(ChangeApprovalDecision).where(
                ChangeApprovalDecision.change_id == change.id,
                ChangeApprovalDecision.approver_id == principal.user_id,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_8215", message="您已经审批过该变更", status_code=409)
        decision = ChangeApprovalDecision(
            change_id=change.id,
            tenant_id=change.tenant_id,
            decision=payload.decision,
            approver_id=principal.user_id,
            comment=payload.comment.strip(),
        )
        session.add(decision)
        await session.flush()
        if payload.decision == "rejected":
            change.status = "rejected"
        else:
            approved_count = await session.scalar(
                select(func.count())
                .select_from(ChangeApprovalDecision)
                .where(
                    ChangeApprovalDecision.change_id == change.id,
                    ChangeApprovalDecision.decision == "approved",
                )
            )
            if (approved_count or 0) >= change.required_approvals:
                change.status = "approved"
                change.approved_at = now
        _append_timeline(
            change,
            principal.user_id,
            change.status,
            "变更审批已处理",
            {"decision": payload.decision},
        )
        await append_audit(
            session,
            request,
            action="change.approval.decided",
            resource_type="change",
            outcome="success",
            principal=principal,
            project_id=change.project_id,
            resource_id=str(change.id),
            metadata={"decision": payload.decision, "resulting_status": change.status},
        )
        await session.flush()
        await session.refresh(change)
    return ChangeResponse.model_validate(change)


@router.post("/{change_id}/status", response_model=ChangeResponse)
async def change_status(
    change_id: UUID,
    payload: ChangeStatusUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("change:execute"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeResponse:
    now = datetime.now(UTC)
    async with session.begin():
        change = await get_change_in_scope(
            session, tenant_id=principal.tenant_id, change_id=change_id, for_update=True
        )
        ensure_project_scope(principal, change.project_id)
        await require_automation_job_ref(
            session,
            tenant_id=principal.tenant_id,
            project_id=change.project_id,
            job_id=payload.automation_job_id,
        )
        validate_status_transition(change.status, payload.status)
        if payload.status == "in_progress":
            if change.risk_level in {"R2", "R3"} or change.gxp_impact:
                if change.approved_at is None:
                    raise ApplicationError(
                        code="AIOPS_8216", message="受控变更尚未获得有效审批", status_code=409
                    )
                if not change.scheduled_start or not change.scheduled_end:
                    raise ApplicationError(
                        code="AIOPS_8217", message="受控变更必须设置维护时间窗口", status_code=409
                    )
                if not (_as_utc(change.scheduled_start) <= now <= _as_utc(change.scheduled_end)):
                    raise ApplicationError(
                        code="AIOPS_8218", message="当前不在变更维护时间窗口内", status_code=409
                    )
            change.started_at = now
        if payload.status in {"completed", "failed", "rolled_back"}:
            change.completed_at = now
        change.status = payload.status
        change.failure_reason = payload.failure_reason
        if payload.automation_job_id is not None:
            change.automation_job_id = payload.automation_job_id
        _append_timeline(
            change,
            principal.user_id,
            change.status,
            f"变更状态更新为 {change.status}",
            {
                "automation_job_id": str(change.automation_job_id)
                if change.automation_job_id
                else None
            },
        )
        await append_audit(
            session,
            request,
            action="change.status.updated",
            resource_type="change",
            outcome="success",
            principal=principal,
            project_id=change.project_id,
            resource_id=str(change.id),
            metadata={
                "status": change.status,
                "failure_reason_present": bool(change.failure_reason),
            },
        )
        await session.flush()
        await session.refresh(change)
    return ChangeResponse.model_validate(change)


def _append_timeline(
    change: ChangeRequest,
    actor_id: UUID,
    status: str,
    title: str,
    details: dict[str, Any] | None = None,
) -> None:
    change_entry = ChangeTimelineEntry(
        change_id=change.id,
        tenant_id=change.tenant_id,
        occurred_at=datetime.now(UTC),
        status=status,
        title=title,
        details=details or {},
        created_by=actor_id,
    )
    # The mapped object is already attached to a Session after the initial flush.
    from sqlalchemy import inspect

    session = inspect(change).session
    if session is None:
        raise RuntimeError("change must be attached to a session")
    session.add(change_entry)


def _uuid_strings(values: list[UUID] | list[Any]) -> list[str]:
    return [str(value) for value in values]


def _uuid_values(values: list[str]) -> list[UUID]:
    return [UUID(value) for value in values]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
