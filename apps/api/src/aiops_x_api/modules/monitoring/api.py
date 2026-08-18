from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.cmdb.application import (
    get_asset_for_scope,
    update_asset_monitoring_status,
)
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.monitoring.application import (
    build_alert_expression,
    collect_node_metric_history,
    collect_node_metrics,
    get_binding_for_asset,
    record_collector_result,
    validate_target_instance,
    verify_target,
)
from aiops_x_api.modules.monitoring.contracts import MetricSample, MetricsBackend
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from aiops_x_api.modules.monitoring.infrastructure.models import (
    AlertRule,
    AlertRuleVersion,
    AssetMonitorBinding,
    MonitorTarget,
)
from aiops_x_api.modules.monitoring.schemas import (
    AlertRuleCreate,
    AlertRulePage,
    AlertRuleResponse,
    AlertRuleVersionInput,
    AlertRuleVersionResponse,
    MetricPointResponse,
    MetricSampleResponse,
    MetricSeriesResponse,
    MonitorBindingResponse,
    MonitorTargetCreate,
    MonitorTargetPage,
    MonitorTargetResponse,
    MonitorTargetUpdate,
    MonitorTargetVerificationResponse,
    NodeMetricHistoryResponse,
    NodeMetricsResponse,
)
from aiops_x_api.modules.tenant.application import (
    get_tenant_scope_by_id,
    require_project_scope,
)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/alert-rules", response_model=AlertRulePage)
async def list_alert_rules(
    principal: Annotated[Principal, Depends(require_permission("rule:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> AlertRulePage:
    filters = [AlertRule.tenant_id == principal.tenant_id]
    allowed = scoped_project_ids(principal)
    if allowed is not None:
        filters.append(AlertRule.project_id.in_(allowed))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(AlertRule.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(AlertRule).where(*filters))
    rows = (
        await session.execute(
            select(AlertRule, AlertRuleVersion)
            .join(
                AlertRuleVersion,
                (AlertRuleVersion.alert_rule_id == AlertRule.id)
                & (AlertRuleVersion.version == AlertRule.current_version),
            )
            .where(*filters)
            .order_by(AlertRule.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AlertRulePage(
        items=[_alert_rule_response(rule, version) for rule, version in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("rule:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    ensure_project_scope(principal, payload.project_id)
    project = await require_project_scope(
        session, tenant_id=principal.tenant_id, project_id=payload.project_id
    )
    tenant = await get_tenant_scope_by_id(session, principal.tenant_id)
    existing = await session.scalar(
        select(AlertRule.id).where(
            AlertRule.tenant_id == principal.tenant_id,
            AlertRule.project_id == payload.project_id,
            AlertRule.slug == payload.slug,
        )
    )
    if existing is not None:
        raise ApplicationError(code="AIOPS_5221", message="告警规则标识已存在", status_code=409)
    rule = AlertRule(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        slug=payload.slug,
        name=payload.name,
        enabled=True,
        current_version=1,
        created_by=principal.user_id,
    )
    session.add(rule)
    await session.flush()
    version = _new_rule_version(
        rule=rule,
        version=1,
        payload=payload,
        tenant_slug=tenant.slug,
        project_slug=project.slug,
        created_by=principal.user_id,
    )
    session.add(version)
    await append_audit(
        session,
        request,
        action="monitoring.alert_rule.created",
        resource_type="alert_rule",
        outcome="success",
        principal=principal,
        project_id=project.id,
        resource_id=str(rule.id),
        metadata={"version": 1, "metric_key": version.metric_key},
    )
    await session.commit()
    return _alert_rule_response(rule, version)


@router.post("/alert-rules/{rule_id}/versions", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule_version(
    rule_id: UUID,
    payload: AlertRuleVersionInput,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("rule:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    rule = await _alert_rule_in_scope(session, principal, rule_id, lock=True)
    project = await require_project_scope(
        session, tenant_id=principal.tenant_id, project_id=rule.project_id
    )
    tenant = await get_tenant_scope_by_id(session, principal.tenant_id)
    rule.current_version += 1
    version = _new_rule_version(
        rule=rule,
        version=rule.current_version,
        payload=payload,
        tenant_slug=tenant.slug,
        project_slug=project.slug,
        created_by=principal.user_id,
    )
    session.add(version)
    await append_audit(
        session,
        request,
        action="monitoring.alert_rule.version_created",
        resource_type="alert_rule",
        outcome="success",
        principal=principal,
        project_id=rule.project_id,
        resource_id=str(rule.id),
        metadata={"version": version.version},
    )
    await session.commit()
    return _alert_rule_response(rule, version)


@router.post(
    "/alert-rules/{rule_id}/versions/{version_number}/publish",
    response_model=AlertRuleResponse,
)
async def publish_alert_rule_version(
    rule_id: UUID,
    version_number: int,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("rule:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertRuleResponse:
    rule = await _alert_rule_in_scope(session, principal, rule_id, lock=True)
    version = await session.scalar(
        select(AlertRuleVersion).where(
            AlertRuleVersion.alert_rule_id == rule.id,
            AlertRuleVersion.version == version_number,
        )
    )
    if version is None:
        raise ApplicationError(code="AIOPS_5222", message="告警规则版本不存在", status_code=404)
    previous = (
        await session.scalars(
            select(AlertRuleVersion).where(
                AlertRuleVersion.alert_rule_id == rule.id,
                AlertRuleVersion.status == "published",
            )
        )
    ).all()
    for item in previous:
        item.status = "retired"
    version.status = "published"
    version.published_at = datetime.now(UTC)
    rule.published_version = version.version
    await append_audit(
        session,
        request,
        action="monitoring.alert_rule.published",
        resource_type="alert_rule",
        outcome="success",
        principal=principal,
        project_id=rule.project_id,
        resource_id=str(rule.id),
        metadata={"version": version.version},
    )
    await session.commit()
    return _alert_rule_response(rule, version)


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
    validate_target_instance(payload.prometheus_instance, asset)
    project = await require_project_scope(
        session, tenant_id=principal.tenant_id, project_id=payload.project_id
    )
    tenant = await get_tenant_scope_by_id(session, principal.tenant_id)
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
    if payload.prometheus_instance is not None:
        asset = await get_asset_for_scope(
            session, tenant_id=principal.tenant_id, asset_id=binding.asset_id
        )
        validate_target_instance(payload.prometheus_instance, asset)
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
        await record_collector_result(
            session,
            target=target,
            binding=binding,
            checked_at=checked_at,
            sample_at=None,
            healthy=False,
            error_code=exc.code,
        )
        await update_asset_monitoring_status(
            session,
            tenant_id=principal.tenant_id,
            asset_id=binding.asset_id,
            monitoring_status="error",
        )
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
    target_up = verified.up_sample.value == 1.0
    await record_collector_result(
        session,
        target=target,
        binding=binding,
        checked_at=checked_at,
        sample_at=verified.up_sample.observed_at,
        healthy=target_up,
        error_code=None if target_up else "AIOPS_TARGET_DOWN",
    )
    await update_asset_monitoring_status(
        session,
        tenant_id=principal.tenant_id,
        asset_id=binding.asset_id,
        monitoring_status="active" if target_up else "degraded",
        last_monitored_at=verified.up_sample.observed_at,
    )
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
        target_up=target_up,
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
    target_up = verified.up_sample.value == 1.0
    await record_collector_result(
        session,
        target=target,
        binding=binding,
        checked_at=verified.verified_at,
        sample_at=verified.up_sample.observed_at,
        healthy=target_up,
        error_code=None if target_up else "AIOPS_TARGET_DOWN",
    )
    await update_asset_monitoring_status(
        session,
        tenant_id=principal.tenant_id,
        asset_id=asset.id,
        monitoring_status="active" if target_up else "degraded",
        last_monitored_at=verified.up_sample.observed_at,
    )
    await session.commit()
    age = max(0.0, (verified.verified_at - verified.up_sample.observed_at).total_seconds())
    return NodeMetricsResponse(
        asset_id=asset.id,
        target_id=target.id,
        binding_id=binding.id,
        collected_at=verified.verified_at,
        sample_timestamp=verified.up_sample.observed_at,
        age_seconds=round(age, 3),
        target_up=target_up,
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


@router.get(
    "/assets/{asset_id}/node-metrics/history",
    response_model=NodeMetricHistoryResponse,
)
async def get_node_metric_history(
    asset_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("metrics:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    backend: Annotated[MetricsBackend, Depends(get_metrics_backend)],
    metric: Annotated[
        Literal[
            "cpu",
            "memory",
            "filesystem",
            "load1",
            "uptime_seconds",
            "network_receive_bytes",
            "network_transmit_bytes",
            "disk_read_bytes",
            "disk_write_bytes",
        ],
        Query(),
    ],
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    step_seconds: Annotated[int, Query(ge=15, le=3600)] = 60,
) -> NodeMetricHistoryResponse:
    if start.tzinfo is None or end.tzinfo is None:
        raise ApplicationError(
            code="AIOPS_5213", message="历史查询时间必须包含时区", status_code=422
        )
    if start >= end or (end - start).total_seconds() > 7 * 86400:
        raise ApplicationError(
            code="AIOPS_5214", message="历史查询时间窗必须大于零且不超过 7 天", status_code=422
        )
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
    _, series = await collect_node_metric_history(
        backend,
        target=target,
        binding=binding,
        metric=metric,
        start=start,
        end=end,
        step_seconds=step_seconds,
    )
    return NodeMetricHistoryResponse(
        asset_id=asset.id,
        target_id=target.id,
        metric_name=metric,
        start=start,
        end=end,
        step_seconds=step_seconds,
        series=[
            MetricSeriesResponse(
                metric=item.metric,
                points=[
                    MetricPointResponse(timestamp=point.observed_at, value=point.value)
                    for point in item.points
                ],
            )
            for item in series
        ],
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


async def _alert_rule_in_scope(
    session: AsyncSession, principal: Principal, rule_id: UUID, *, lock: bool
) -> AlertRule:
    statement = select(AlertRule).where(
        AlertRule.id == rule_id, AlertRule.tenant_id == principal.tenant_id
    )
    if lock:
        statement = statement.with_for_update()
    rule = await session.scalar(statement)
    if rule is None:
        raise ApplicationError(code="AIOPS_5223", message="告警规则不存在", status_code=404)
    ensure_project_scope(principal, rule.project_id)
    return rule


def _new_rule_version(
    *,
    rule: AlertRule,
    version: int,
    payload: AlertRuleVersionInput,
    tenant_slug: str,
    project_slug: str,
    created_by: UUID,
) -> AlertRuleVersion:
    expression = build_alert_expression(
        metric_key=payload.metric_key,
        operator=payload.operator,
        threshold=payload.threshold,
        tenant_slug=tenant_slug,
        project_slug=project_slug,
    )
    return AlertRuleVersion(
        alert_rule_id=rule.id,
        version=version,
        metric_key=payload.metric_key,
        operator=payload.operator,
        threshold=payload.threshold,
        duration_seconds=payload.duration_seconds,
        severity=payload.severity,
        expression=expression,
        labels={
            "severity": payload.severity,
            "service": "node-observability",
            "aiops_rule_id": str(rule.id),
        },
        annotations={
            "summary": payload.summary,
            "description": payload.description,
            "evidence_query": expression,
        },
        status="draft",
        created_by=created_by,
    )


def _alert_rule_response(rule: AlertRule, version: AlertRuleVersion) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=rule.id,
        tenant_id=rule.tenant_id,
        project_id=rule.project_id,
        slug=rule.slug,
        name=rule.name,
        enabled=rule.enabled,
        current_version=rule.current_version,
        published_version=rule.published_version,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        version=AlertRuleVersionResponse.model_validate(version),
    )


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
