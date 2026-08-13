from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.monitoring.application import (
    collect_node_metrics,
    get_binding_for_asset,
    verify_target,
)
from aiops_x_api.modules.monitoring.contracts import MetricSample, MetricsBackend
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from aiops_x_api.modules.monitoring.infrastructure.models import AssetMonitorBinding, MonitorTarget
from aiops_x_api.modules.monitoring.schemas import (
    MetricSampleResponse,
    MonitorBindingResponse,
    MonitorTargetCreate,
    MonitorTargetPage,
    MonitorTargetResponse,
    MonitorTargetUpdate,
    MonitorTargetVerificationResponse,
    NodeMetricsResponse,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant
from aiops_x_api.modules.tenant.infrastructure.models import Tenant

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/targets", response_model=MonitorTargetPage)
async def list_monitor_targets(
    principal: Annotated[Principal, Depends(require_permission("metrics:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> MonitorTargetPage:
    filters = [MonitorTarget.tenant_id == principal.tenant_id]
    allowed = scoped_project_ids(principal)
    if allowed is not None:
        filters.append(MonitorTarget.project_id.in_(allowed))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(MonitorTarget.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(MonitorTarget).where(*filters))
    rows = (
        await session.execute(
            select(MonitorTarget, AssetMonitorBinding)
            .join(
                AssetMonitorBinding,
                AssetMonitorBinding.monitor_target_id == MonitorTarget.id,
            )
            .where(*filters)
            .order_by(MonitorTarget.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MonitorTargetPage(
        items=[_target_response(target, binding) for target, binding in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/targets", response_model=MonitorTargetResponse, status_code=201)
async def create_monitor_target(
    payload: MonitorTargetCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("metrics:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MonitorTargetResponse:
    ensure_project_scope(principal, payload.project_id)
    asset = await get_asset_for_scope(
        session, tenant_id=principal.tenant_id, asset_id=payload.asset_id
    )
    if asset.project_id != payload.project_id:
        raise ApplicationError(
            code="AIOPS_5210", message="监控目标与资产项目范围不一致", status_code=422
        )
    ensure_asset_scope(
        principal,
        project_id=asset.project_id,
        environment=asset.environment,
        tags=asset.tags,
        gxp_classification=asset.gxp_classification,
    )
    project = await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise ApplicationError(code="AIOPS_2004", message="租户不存在", status_code=404)
    try:
        async with session.begin_nested():
            target = MonitorTarget(
                tenant_id=principal.tenant_id,
                project_id=project.id,
                name=payload.name.strip(),
                target_type=payload.target_type,
                prometheus_job=payload.prometheus_job,
                prometheus_instance=payload.prometheus_instance,
                tenant_slug=tenant.slug,
                project_slug=project.slug,
                enabled=True,
                created_by=principal.user_id,
            )
            session.add(target)
            await session.flush()
            binding = AssetMonitorBinding(
                tenant_id=principal.tenant_id,
                project_id=project.id,
                asset_id=asset.id,
                monitor_target_id=target.id,
                purpose=payload.purpose,
                identity_label=payload.identity_label,
                identity_value=asset.asset_id,
                enabled=True,
                verification_status="unverified",
                created_by=principal.user_id,
            )
            session.add(binding)
            await session.flush()
    except IntegrityError as exc:
        raise ApplicationError(
            code="AIOPS_5211",
            message="资产或 Prometheus 目标已存在唯一监控绑定",
            status_code=409,
        ) from exc
    await append_audit(
        session,
        request,
        action="monitoring.target.created",
        resource_type="monitor_target",
        outcome="success",
        principal=principal,
        project_id=project.id,
        resource_id=str(target.id),
        metadata={"asset_id": str(asset.id), "target_type": target.target_type},
    )
    await session.commit()
    return _target_response(target, binding)


@router.patch("/targets/{target_id}", response_model=MonitorTargetResponse)
async def update_monitor_target(
    target_id: UUID,
    payload: MonitorTargetUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("metrics:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MonitorTargetResponse:
    target, binding = await _target_in_scope(session, principal, target_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(target, field, value)
    if "enabled" in changes:
        binding.enabled = bool(changes["enabled"])
    binding.verification_status = "unverified"
    binding.last_verified_at = None
    binding.last_error_code = None
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApplicationError(
            code="AIOPS_5211", message="Prometheus 目标已被其他资产绑定", status_code=409
        ) from exc
    await append_audit(
        session,
        request,
        action="monitoring.target.updated",
        resource_type="monitor_target",
        outcome="success",
        principal=principal,
        project_id=target.project_id,
        resource_id=str(target.id),
        metadata={"changed_fields": sorted(changes)},
    )
    await session.commit()
    return _target_response(target, binding)


@router.post("/targets/{target_id}/verify", response_model=MonitorTargetVerificationResponse)
async def verify_monitor_target(
    target_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("metrics:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    backend: Annotated[MetricsBackend, Depends(get_metrics_backend)],
) -> MonitorTargetVerificationResponse:
    target, binding = await _target_in_scope(session, principal, target_id, lock=False)
    checked_at = datetime.now(UTC)
    try:
        verified = await verify_target(backend, target=target, binding=binding, now=checked_at)
    except ApplicationError as exc:
        binding.verification_status = "failed"
        binding.last_verified_at = checked_at
        binding.last_error_code = exc.code
        await append_audit(
            session,
            request,
            action="monitoring.target.verification_failed",
            resource_type="monitor_target",
            outcome="failure",
            principal=principal,
            project_id=target.project_id,
            resource_id=str(target.id),
            metadata={"error_code": exc.code},
        )
        await session.commit()
        raise
    binding.verification_status = "verified"
    binding.last_verified_at = checked_at
    binding.last_error_code = None
    await append_audit(
        session,
        request,
        action="monitoring.target.verified",
        resource_type="monitor_target",
        outcome="success",
        principal=principal,
        project_id=target.project_id,
        resource_id=str(target.id),
        metadata={"asset_id": str(binding.asset_id)},
    )
    await session.commit()
    return MonitorTargetVerificationResponse(
        target_id=target.id,
        binding_id=binding.id,
        status="verified",
        verified_at=verified.verified_at,
        error_code=None,
        sample_timestamp=verified.up_sample.observed_at,
        target_up=verified.up_sample.value == 1.0,
    )


@router.get("/assets/{asset_id}/node-metrics", response_model=NodeMetricsResponse)
async def get_node_metrics(
    asset_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("metrics:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    backend: Annotated[MetricsBackend, Depends(get_metrics_backend)],
) -> NodeMetricsResponse:
    asset, target, binding = await get_binding_for_asset(
        session, tenant_id=principal.tenant_id, asset_id=asset_id
    )
    ensure_asset_scope(
        principal,
        project_id=asset.project_id,
        environment=asset.environment,
        tags=asset.tags,
        gxp_classification=asset.gxp_classification,
    )
    verified, samples = await collect_node_metrics(backend, target=target, binding=binding)
    binding.verification_status = "verified"
    binding.last_verified_at = verified.verified_at
    binding.last_error_code = None
    await session.commit()
    age = max(0.0, (verified.verified_at - verified.up_sample.observed_at).total_seconds())
    return NodeMetricsResponse(
        asset_id=asset.id,
        target_id=target.id,
        binding_id=binding.id,
        collected_at=verified.verified_at,
        sample_timestamp=verified.up_sample.observed_at,
        age_seconds=round(age, 3),
        target_up=verified.up_sample.value == 1.0,
        cpu_usage_percent=_first_value(samples["cpu"]),
        memory_usage_percent=_first_value(samples["memory"]),
        root_filesystem_usage_percent=_first_value(samples["filesystem"]),
        raw_samples={
            name: [
                MetricSampleResponse(
                    metric=sample.metric,
                    timestamp=sample.observed_at,
                    value=sample.value,
                )
                for sample in values
            ]
            for name, values in samples.items()
        },
    )


async def _target_in_scope(
    session: AsyncSession, principal: Principal, target_id: UUID, *, lock: bool
) -> tuple[MonitorTarget, AssetMonitorBinding]:
    statement = (
        select(MonitorTarget, AssetMonitorBinding)
        .join(
            AssetMonitorBinding,
            AssetMonitorBinding.monitor_target_id == MonitorTarget.id,
        )
        .where(MonitorTarget.id == target_id, MonitorTarget.tenant_id == principal.tenant_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise ApplicationError(code="AIOPS_5204", message="监控目标不存在", status_code=404)
    target, binding = row
    ensure_project_scope(principal, target.project_id)
    return target, binding


def _target_response(target: MonitorTarget, binding: AssetMonitorBinding) -> MonitorTargetResponse:
    return MonitorTargetResponse(
        id=target.id,
        tenant_id=target.tenant_id,
        project_id=target.project_id,
        name=target.name,
        target_type=target.target_type,
        prometheus_job=target.prometheus_job,
        prometheus_instance=target.prometheus_instance,
        tenant_slug=target.tenant_slug,
        project_slug=target.project_slug,
        enabled=target.enabled,
        created_at=target.created_at,
        updated_at=target.updated_at,
        binding=MonitorBindingResponse.model_validate(binding),
    )


def _first_value(samples: list[MetricSample]) -> float | None:
    return samples[0].value if samples else None
