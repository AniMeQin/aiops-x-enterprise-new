from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.reliability.infrastructure.models import (
    CapacityAnalysis,
    ServiceLevelObjective,
    SloEvaluation,
)
from aiops_x_api.modules.reliability.schemas import (
    CapacityAnalysisCreate,
    CapacityAnalysisPage,
    CapacityAnalysisResponse,
    SloCreate,
    SloEvaluationResponse,
    SloPage,
    SloResponse,
)
from aiops_x_api.modules.telemetry.adapters import backend_json_request
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/reliability", tags=["reliability"])


@router.get("/slos", response_model=SloPage)
async def list_slos(
    principal: Annotated[Principal, Depends(require_permission("slo:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> SloPage:
    filters = [ServiceLevelObjective.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(ServiceLevelObjective.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(ServiceLevelObjective.project_id == project_id)
    total = await session.scalar(
        select(func.count()).select_from(ServiceLevelObjective).where(*filters)
    )
    rows = (
        await session.scalars(
            select(ServiceLevelObjective)
            .where(*filters)
            .order_by(ServiceLevelObjective.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return SloPage(
        items=[SloResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/slos", response_model=SloResponse, status_code=201)
async def create_slo(
    payload: SloCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("slo:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SloResponse:
    ensure_project_scope(principal, payload.project_id)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        existing = await session.scalar(
            select(ServiceLevelObjective.id).where(
                ServiceLevelObjective.tenant_id == principal.tenant_id,
                ServiceLevelObjective.project_id == payload.project_id,
                ServiceLevelObjective.name == payload.name,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_8502", message="同名 SLO 已存在", status_code=409)
        slo = ServiceLevelObjective(
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            **payload.model_dump(),
        )
        session.add(slo)
        await session.flush()
        await append_audit(
            session,
            request,
            action="slo.created",
            resource_type="slo",
            outcome="success",
            principal=principal,
            project_id=slo.project_id,
            resource_id=str(slo.id),
            metadata={"target": slo.target, "window_days": slo.window_days},
        )
    return SloResponse.model_validate(slo)


@router.post("/slos/{slo_id}/evaluate", response_model=SloEvaluationResponse)
async def evaluate_slo(
    slo_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("slo:evaluate"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SloEvaluationResponse:
    slo = await session.scalar(
        select(ServiceLevelObjective).where(
            ServiceLevelObjective.id == slo_id,
            ServiceLevelObjective.tenant_id == principal.tenant_id,
            ServiceLevelObjective.enabled.is_(True),
        )
    )
    if slo is None:
        raise ApplicationError(code="AIOPS_8504", message="SLO 不存在或已停用", status_code=404)
    ensure_project_scope(principal, slo.project_id)
    evaluated_slo_id = slo.id
    evaluated_tenant_id = slo.tenant_id
    evaluated_project_id = slo.project_id
    target = slo.target
    warning_burn_rate = slo.warning_burn_rate
    critical_burn_rate = slo.critical_burn_rate
    prometheus_query = slo.prometheus_query
    query_time = datetime.now(UTC)
    payload = await backend_json_request(
        backend="Prometheus",
        base_url=get_settings().prometheus_url,
        path="/api/v1/query",
        parameters={"query": prometheus_query, "time": query_time.timestamp()},
    )
    indicator, sample = _prometheus_instant_value(payload)
    if not 0 <= indicator <= 1:
        raise ApplicationError(
            code="AIOPS_8505", message="SLO 指标查询结果必须介于 0 和 1 之间", status_code=502
        )
    allowed_error = 1 - target
    actual_error = 1 - indicator
    burn_rate = actual_error / allowed_error
    budget_remaining = max(0.0, min(1.0, 1 - burn_rate))
    status = (
        "critical"
        if burn_rate >= critical_burn_rate
        else "warning"
        if burn_rate >= warning_burn_rate
        else "healthy"
    )
    await session.rollback()
    async with session.begin():
        evaluation = SloEvaluation(
            tenant_id=evaluated_tenant_id,
            project_id=evaluated_project_id,
            slo_id=evaluated_slo_id,
            status=status,
            indicator_value=indicator,
            target=target,
            error_budget_remaining=budget_remaining,
            burn_rate=burn_rate,
            query_time=query_time,
            source_ref="prometheus://api/v1/query",
            raw_sample=sample,
        )
        session.add(evaluation)
        await session.flush()
        await append_audit(
            session,
            request,
            action="slo.evaluated",
            resource_type="slo",
            outcome="success",
            principal=principal,
            project_id=evaluated_project_id,
            resource_id=str(evaluated_slo_id),
            metadata={"status": status, "indicator_value": indicator, "burn_rate": burn_rate},
        )
    return SloEvaluationResponse.model_validate(evaluation)


@router.get("/capacity", response_model=CapacityAnalysisPage)
async def list_capacity_analyses(
    principal: Annotated[Principal, Depends(require_permission("capacity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> CapacityAnalysisPage:
    filters = [CapacityAnalysis.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(CapacityAnalysis.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(CapacityAnalysis.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(CapacityAnalysis).where(*filters))
    rows = (
        await session.scalars(
            select(CapacityAnalysis)
            .where(*filters)
            .order_by(CapacityAnalysis.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return CapacityAnalysisPage(
        items=[CapacityAnalysisResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/capacity/analyze", response_model=CapacityAnalysisResponse, status_code=201)
async def analyze_capacity(
    payload: CapacityAnalysisCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("capacity:analyze"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CapacityAnalysisResponse:
    ensure_project_scope(principal, payload.project_id)
    await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
    end_time = datetime.now(UTC)
    start_time = end_time - timedelta(hours=payload.lookback_hours)
    step = max(60, min(3600, payload.lookback_hours * 3600 // 500))
    prometheus = await backend_json_request(
        backend="Prometheus",
        base_url=get_settings().prometheus_url,
        path="/api/v1/query_range",
        parameters={
            "query": payload.prometheus_query,
            "start": start_time.timestamp(),
            "end": end_time.timestamp(),
            "step": step,
        },
    )
    points = _prometheus_range_values(prometheus)
    result = _capacity_result(
        points, payload.forecast_hours, payload.warning_threshold, payload.critical_threshold
    )
    await session.rollback()
    async with session.begin():
        analysis = CapacityAnalysis(
            analysis_id=f"CAP-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}",
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            name=payload.name,
            resource_type=payload.resource_type,
            service_ref=payload.service_ref,
            prometheus_query=payload.prometheus_query,
            lookback_hours=payload.lookback_hours,
            forecast_hours=payload.forecast_hours,
            warning_threshold=payload.warning_threshold,
            critical_threshold=payload.critical_threshold,
            status=str(result["status"]),
            result=result,
            source_ref="prometheus://api/v1/query_range",
            created_by=principal.user_id,
        )
        session.add(analysis)
        await session.flush()
        await append_audit(
            session,
            request,
            action="capacity.analysis.completed",
            resource_type="capacity_analysis",
            outcome="success",
            principal=principal,
            project_id=analysis.project_id,
            resource_id=str(analysis.id),
            metadata={"status": analysis.status, "sample_count": len(points)},
        )
    return CapacityAnalysisResponse.model_validate(analysis)


def _prometheus_instant_value(payload: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), list) or not data["result"]:
        raise ApplicationError(
            code="AIOPS_8506", message="Prometheus 未返回 SLO 样本", status_code=422
        )
    sample = data["result"][0]
    if not isinstance(sample, dict) or not isinstance(sample.get("value"), list):
        raise ApplicationError(
            code="AIOPS_8507", message="Prometheus SLO 样本结构无效", status_code=502
        )
    try:
        return float(sample["value"][1]), {
            "metric": sample.get("metric", {}),
            "timestamp": sample["value"][0],
        }
    except (IndexError, TypeError, ValueError) as exc:
        raise ApplicationError(
            code="AIOPS_8507", message="Prometheus SLO 样本结构无效", status_code=502
        ) from exc


def _prometheus_range_values(payload: dict[str, Any]) -> list[tuple[float, float]]:
    data = payload.get("data")
    results = data.get("result") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        raise ApplicationError(
            code="AIOPS_8510", message="Prometheus 未返回容量样本", status_code=422
        )
    points: list[tuple[float, float]] = []
    for series in results:
        if not isinstance(series, dict) or not isinstance(series.get("values"), list):
            continue
        for raw in series["values"]:
            if not isinstance(raw, list) or len(raw) != 2:
                continue
            try:
                points.append((float(raw[0]), float(raw[1])))
            except (TypeError, ValueError):
                continue
    if len(points) < 2:
        raise ApplicationError(
            code="AIOPS_8511", message="容量分析至少需要两个有效样本", status_code=422
        )
    points.sort(key=lambda item: item[0])
    return points


def _capacity_result(
    points: list[tuple[float, float]], forecast_hours: int, warning: float, critical: float
) -> dict[str, Any]:
    times = [point[0] for point in points]
    values = [point[1] for point in points]
    mean_time = fmean(times)
    mean_value = fmean(values)
    denominator = sum((item - mean_time) ** 2 for item in times)
    slope_per_second = (
        sum((time - mean_time) * (value - mean_value) for time, value in points) / denominator
        if denominator
        else 0.0
    )
    forecast_value = values[-1] + slope_per_second * forecast_hours * 3600
    projected = max(0.0, forecast_value)
    status = (
        "critical" if projected >= critical else "warning" if projected >= warning else "healthy"
    )
    return {
        "status": status,
        "sample_count": len(points),
        "window_start": datetime.fromtimestamp(times[0], tz=UTC).isoformat(),
        "window_end": datetime.fromtimestamp(times[-1], tz=UTC).isoformat(),
        "minimum": min(values),
        "maximum": max(values),
        "average": mean_value,
        "latest": values[-1],
        "trend_per_hour": slope_per_second * 3600,
        "forecast_hours": forecast_hours,
        "forecast_value": projected,
        "method": "least_squares_linear_trend",
        "warning_threshold": warning,
        "critical_threshold": critical,
    }
