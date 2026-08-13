import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.core.observability import ALERTS_INGESTED
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.automation.contracts import list_event_automation_jobs
from aiops_x_api.modules.cmdb.application import (
    dependency_correlation_key,
    get_asset_by_external_scope,
    get_asset_for_scope,
    update_asset_monitoring_status,
)
from aiops_x_api.modules.cmdb.contracts import AssetView
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.monitoring.application import (
    VerifiedTarget,
    require_alert_binding,
    require_sample_freshness,
    require_sample_identity,
    target_selector,
)
from aiops_x_api.modules.monitoring.contracts import MetricsBackend
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from aiops_x_api.modules.operations.infrastructure.models import (
    Alert,
    EventAlert,
    EventTimelineEntry,
    MaintenanceWindow,
    OperationsEvent,
)
from aiops_x_api.modules.operations.schemas import (
    AlertmanagerAlert,
    AlertmanagerWebhook,
    AlertPage,
    AlertResponse,
    EventAsset,
    EventAutomationJob,
    EventDetail,
    EventPage,
    EventResponse,
    MaintenanceWindowCreate,
    MaintenanceWindowPage,
    MaintenanceWindowResponse,
    MaintenanceWindowUpdate,
    TimelineEntryResponse,
    WebhookResult,
)
from aiops_x_api.modules.tenant.application import require_project_scope, resolve_project_scope
from aiops_x_api.modules.tenant.contracts import ProjectScope, TenantScope

router = APIRouter(tags=["operations"])
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


@router.get("/maintenance-windows", response_model=MaintenanceWindowPage)
async def list_maintenance_windows(
    principal: Annotated[Principal, Depends(require_permission("maintenance:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> MaintenanceWindowPage:
    filters = [MaintenanceWindow.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(MaintenanceWindow.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(MaintenanceWindow.project_id == project_id)
    if enabled is not None:
        filters.append(MaintenanceWindow.enabled == enabled)
    total = await session.scalar(
        select(func.count()).select_from(MaintenanceWindow).where(*filters)
    )
    rows = (
        await session.scalars(
            select(MaintenanceWindow)
            .where(*filters)
            .order_by(MaintenanceWindow.starts_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MaintenanceWindowPage(
        items=[MaintenanceWindowResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/maintenance-windows", response_model=MaintenanceWindowResponse, status_code=201)
async def create_maintenance_window(
    payload: MaintenanceWindowCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("maintenance:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWindowResponse:
    ensure_project_scope(principal, payload.project_id)
    starts_at, ends_at = _validated_window_range(payload.starts_at, payload.ends_at)
    async with session.begin():
        await require_project_scope(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
        )
        if payload.asset_id is not None:
            asset = await get_asset_for_scope(
                session, tenant_id=principal.tenant_id, asset_id=payload.asset_id
            )
            if asset.project_id != payload.project_id:
                raise ApplicationError(
                    code="AIOPS_3104", message="资产不存在或与项目范围不匹配", status_code=404
                )
        window = MaintenanceWindow(
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            asset_id=payload.asset_id,
            name=payload.name.strip(),
            starts_at=starts_at,
            ends_at=ends_at,
            enabled=True,
            created_by=principal.user_id,
        )
        session.add(window)
        await session.flush()
        await append_audit(
            session,
            request,
            action="maintenance_window.created",
            resource_type="maintenance_window",
            outcome="success",
            principal=principal,
            project_id=window.project_id,
            resource_id=str(window.id),
            metadata={"asset_id": str(window.asset_id) if window.asset_id else None},
        )
    return MaintenanceWindowResponse.model_validate(window)


@router.patch("/maintenance-windows/{window_id}", response_model=MaintenanceWindowResponse)
async def update_maintenance_window(
    window_id: UUID,
    payload: MaintenanceWindowUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("maintenance:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MaintenanceWindowResponse:
    async with session.begin():
        window = await session.scalar(
            select(MaintenanceWindow)
            .where(
                MaintenanceWindow.id == window_id,
                MaintenanceWindow.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if window is None:
            raise ApplicationError(code="AIOPS_6105", message="维护窗口不存在", status_code=404)
        ensure_project_scope(principal, window.project_id)
        starts_at, ends_at = _validated_window_range(
            payload.starts_at or window.starts_at, payload.ends_at or window.ends_at
        )
        changes = payload.model_dump(exclude_unset=True)
        window.starts_at = starts_at
        window.ends_at = ends_at
        if payload.name is not None:
            window.name = payload.name.strip()
        if payload.enabled is not None:
            window.enabled = payload.enabled
        await append_audit(
            session,
            request,
            action="maintenance_window.updated",
            resource_type="maintenance_window",
            outcome="success",
            principal=principal,
            project_id=window.project_id,
            resource_id=str(window.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(window)
    return MaintenanceWindowResponse.model_validate(window)


@router.post("/webhooks/alertmanager", response_model=WebhookResult)
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    backend: Annotated[MetricsBackend, Depends(get_metrics_backend)],
) -> WebhookResult:
    _verify_webhook_authorization(request)
    counters = {"created": 0, "deduplicated": 0, "resolved": 0, "suppressed": 0}
    event_ids: set[str] = set()
    async with session.begin():
        for incoming in payload.alerts:
            event_id, outcome = await _ingest_alert(session, backend, request, incoming)
            counters[outcome] += 1
            ALERTS_INGESTED.labels(outcome).inc()
            if event_id is not None:
                event_ids.add(event_id)
    return WebhookResult(received=len(payload.alerts), event_ids=sorted(event_ids), **counters)


@router.get("/alerts", response_model=AlertPage)
async def list_alerts(
    principal: Annotated[Principal, Depends(require_permission("alert:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> AlertPage:
    filters = [Alert.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Alert.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(Alert.project_id == project_id)
    if status:
        filters.append(Alert.status == status)
    total = await session.scalar(select(func.count()).select_from(Alert).where(*filters))
    alerts = (
        await session.scalars(
            select(Alert)
            .where(*filters)
            .order_by(Alert.last_received_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AlertPage(
        items=[AlertResponse.model_validate(item) for item in alerts],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.get("/events", response_model=EventPage)
async def list_events(
    principal: Annotated[Principal, Depends(require_permission("event:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> EventPage:
    filters = [OperationsEvent.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(OperationsEvent.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(OperationsEvent.project_id == project_id)
    if status:
        filters.append(OperationsEvent.status == status)
    total = await session.scalar(select(func.count()).select_from(OperationsEvent).where(*filters))
    events = (
        await session.scalars(
            select(OperationsEvent)
            .where(*filters)
            .order_by(OperationsEvent.last_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return EventPage(
        items=[EventResponse.model_validate(item) for item in events],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.get("/events/{event_id}", response_model=EventDetail)
async def get_event_detail(
    event_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("event:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventDetail:
    event = await session.scalar(
        select(OperationsEvent).where(
            OperationsEvent.id == event_id,
            OperationsEvent.tenant_id == principal.tenant_id,
        )
    )
    if event is None:
        raise ApplicationError(code="AIOPS_5104", message="事件不存在", status_code=404)
    ensure_project_scope(principal, event.project_id)
    asset = await get_asset_for_scope(
        session, tenant_id=principal.tenant_id, asset_id=event.primary_asset_id
    )
    ensure_asset_scope(
        principal,
        project_id=asset.project_id,
        environment=asset.environment,
        tags=asset.tags,
        gxp_classification=asset.gxp_classification,
    )
    alerts = (
        await session.scalars(
            select(Alert)
            .join(EventAlert, EventAlert.alert_id == Alert.id)
            .where(EventAlert.event_id == event.id)
            .order_by(Alert.starts_at.asc())
        )
    ).all()
    timeline = (
        await session.scalars(
            select(EventTimelineEntry)
            .where(EventTimelineEntry.event_id == event.id)
            .order_by(EventTimelineEntry.occurred_at.asc())
        )
    ).all()
    jobs = await list_event_automation_jobs(session, event_id=event.id)
    return EventDetail(
        **EventResponse.model_validate(event).model_dump(),
        asset=EventAsset(
            id=asset.id,
            asset_id=asset.asset_id,
            name=asset.name,
            hostname=asset.hostname,
            ip_addresses=asset.ip_addresses,
            monitoring_status=asset.monitoring_status,
        ),
        alerts=[AlertResponse.model_validate(item) for item in alerts],
        timeline=[TimelineEntryResponse.model_validate(item) for item in timeline],
        automation_jobs=[EventAutomationJob.model_validate(item) for item in jobs],
    )


async def _ingest_alert(
    session: AsyncSession,
    backend: MetricsBackend,
    request: Request,
    incoming: AlertmanagerAlert,
) -> tuple[str | None, str]:
    tenant, project, asset, verified_target = await _resolve_scope(
        session, backend, incoming.labels
    )
    now = datetime.now(UTC)
    severity = _normalize_severity(incoming.labels.get("severity", "warning"))
    fingerprint = _normalized_fingerprint(tenant.id, project.id, asset.id, incoming.labels)
    evidence_refs = await _evidence_refs(incoming, verified_target, backend)
    correlation_key = await dependency_correlation_key(
        session,
        tenant_id=tenant.id,
        project_id=project.id,
        asset_id=asset.id,
        service=incoming.labels.get("service") or incoming.labels.get("job") or "unknown",
    )
    existing = await session.scalar(
        select(Alert)
        .where(
            Alert.tenant_id == tenant.id,
            Alert.source == "alertmanager",
            Alert.fingerprint == fingerprint,
        )
        .with_for_update()
    )
    event = None
    if existing is None:
        alert = Alert(
            alert_id=_human_id("ALT"),
            source="alertmanager",
            external_id=(incoming.fingerprint or incoming.generatorURL or fingerprint)[:255],
            tenant_id=tenant.id,
            project_id=project.id,
            asset_id=asset.id,
            fingerprint=fingerprint,
            source_fingerprint=incoming.fingerprint or "not-provided",
            correlation_key=correlation_key,
            title=(
                incoming.annotations.get("summary")
                or incoming.labels.get("alertname", "未命名告警")
            )[:255],
            description=incoming.annotations.get("description", ""),
            severity=severity,
            status="resolved" if incoming.status == "resolved" else "firing",
            labels=incoming.labels,
            annotations=incoming.annotations,
            starts_at=_as_utc(incoming.startsAt),
            ends_at=_resolved_end(incoming, now),
            received_at=now,
            last_received_at=now,
            evidence_refs=evidence_refs,
            raw_data_ref=incoming.generatorURL[:512] or None,
        )
        session.add(alert)
        await session.flush()
        await update_asset_monitoring_status(
            session,
            tenant_id=tenant.id,
            asset_id=asset.id,
            monitoring_status="alerting" if incoming.status == "firing" else "monitored",
        )
        outcome = "created" if incoming.status == "firing" else "resolved"
    else:
        alert = existing
        alert.last_received_at = now
        alert.labels = incoming.labels
        alert.annotations = incoming.annotations
        alert.evidence_refs = evidence_refs
        alert.duplicate_count += 1
        if incoming.status == "resolved":
            alert.status = "resolved"
            alert.ends_at = _resolved_end(incoming, now)
            await update_asset_monitoring_status(
                session,
                tenant_id=tenant.id,
                asset_id=asset.id,
                monitoring_status="monitored",
            )
            outcome = "resolved"
        else:
            alert.status = "firing"
            alert.ends_at = None
            await update_asset_monitoring_status(
                session,
                tenant_id=tenant.id,
                asset_id=asset.id,
                monitoring_status="alerting",
            )
            outcome = "deduplicated"

    suppressed = await _inside_maintenance_window(session, tenant.id, project.id, asset.id, now)
    if suppressed and incoming.status == "firing":
        alert.status = "suppressed"
        outcome = "suppressed"
    else:
        event = await _correlate_event(session, request, alert, asset, now, outcome)
    await append_audit(
        session,
        request,
        action=f"alert.{outcome}",
        resource_type="alert",
        outcome="success",
        actor_type="integration",
        actor_id="alertmanager",
        tenant_id=tenant.id,
        project_id=project.id,
        resource_id=str(alert.id),
        metadata={
            "alert_id": alert.alert_id,
            "fingerprint": alert.fingerprint,
            "duplicate_count": alert.duplicate_count,
            "asset_id": str(asset.id),
        },
    )
    return (event.event_id if event is not None else None), outcome


async def _correlate_event(
    session: AsyncSession,
    request: Request,
    alert: Alert,
    asset: AssetView,
    now: datetime,
    alert_outcome: str,
) -> OperationsEvent:
    settings = get_settings()
    cutoff = now - timedelta(seconds=settings.alert_correlation_window_seconds)
    event = await session.scalar(
        select(OperationsEvent)
        .join(EventAlert, EventAlert.event_id == OperationsEvent.id)
        .where(EventAlert.alert_id == alert.id)
        .order_by(OperationsEvent.last_seen_at.desc())
        .with_for_update()
    )
    if event is None:
        event = await session.scalar(
            select(OperationsEvent)
            .where(
                OperationsEvent.tenant_id == alert.tenant_id,
                OperationsEvent.project_id == alert.project_id,
                OperationsEvent.correlation_key == alert.correlation_key,
                OperationsEvent.last_seen_at >= cutoff,
            )
            .order_by(OperationsEvent.last_seen_at.desc())
            .with_for_update()
        )
    created = event is None
    if event is None:
        event = OperationsEvent(
            event_id=_human_id("EVT"),
            tenant_id=alert.tenant_id,
            project_id=alert.project_id,
            primary_asset_id=asset.id,
            correlation_key=alert.correlation_key,
            title=alert.title,
            description=alert.description,
            severity=alert.severity,
            status="resolved" if alert.status == "resolved" else "open",
            affected_asset_ids=[str(asset.id)],
            first_seen_at=alert.starts_at,
            last_seen_at=now,
            resolved_at=alert.ends_at,
            ai_summary_status=(
                "pending" if get_settings().ai_provider.strip() else "not_configured"
            ),
        )
        session.add(event)
        await session.flush()
    else:
        event.last_seen_at = now
        if SEVERITY_ORDER[alert.severity] > SEVERITY_ORDER.get(event.severity, 0):
            event.severity = alert.severity
        affected = set(event.affected_asset_ids)
        affected.add(str(asset.id))
        event.affected_asset_ids = sorted(affected)

    link = await session.scalar(
        select(EventAlert.id).where(
            EventAlert.event_id == event.id, EventAlert.alert_id == alert.id
        )
    )
    if link is None:
        session.add(EventAlert(event_id=event.id, alert_id=alert.id))

    if alert.status == "resolved":
        firing_count = await session.scalar(
            select(func.count())
            .select_from(Alert)
            .join(EventAlert, EventAlert.alert_id == Alert.id)
            .where(EventAlert.event_id == event.id, Alert.status == "firing")
        )
        if (firing_count or 0) == 0:
            event.status = "resolved"
            event.resolved_at = alert.ends_at or now
    else:
        event.status = "open"
        event.resolved_at = None

    timeline_title = {
        "created": "收到告警并创建事件",
        "deduplicated": "重复告警已按指纹抑制",
        "resolved": "告警恢复",
    }.get(alert_outcome, "告警状态更新")
    session.add(
        EventTimelineEntry(
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            event_id=event.id,
            occurred_at=now,
            category="alert",
            title=timeline_title,
            description=alert.title,
            source_type="alert",
            source_id=str(alert.id),
            evidence_refs=alert.evidence_refs,
            metadata_json={
                "alert_id": alert.alert_id,
                "fingerprint": alert.fingerprint,
                "status": alert.status,
                "duplicate_count": alert.duplicate_count,
            },
        )
    )
    if created:
        await append_audit(
            session,
            request,
            action="event.auto_created",
            resource_type="event",
            outcome="success",
            actor_type="system",
            actor_id="alert-correlation",
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            resource_id=str(event.id),
            metadata={"event_id": event.event_id, "alert_id": alert.alert_id},
        )
    return event


async def _resolve_scope(
    session: AsyncSession, backend: MetricsBackend, labels: dict[str, str]
) -> tuple[TenantScope, ProjectScope, AssetView, VerifiedTarget]:
    tenant_slug = labels.get("aiops_tenant_slug", "")
    project_slug = labels.get("aiops_project_slug", "")
    external_asset_id = labels.get("aiops_asset_id", "")
    if not tenant_slug or not project_slug or not external_asset_id:
        raise ApplicationError(
            code="AIOPS_5001",
            message="Alertmanager 告警缺少租户、项目或资产范围标签",
            status_code=422,
        )
    tenant, project = await resolve_project_scope(
        session, tenant_slug=tenant_slug, project_slug=project_slug
    )
    asset = await get_asset_by_external_scope(
        session,
        tenant_id=tenant.id,
        project_id=project.id,
        external_asset_id=external_asset_id,
    )
    verified_target = await require_alert_binding(session, backend, asset=asset, labels=labels)
    return tenant, project, asset, verified_target


async def _inside_maintenance_window(
    session: AsyncSession,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    now: datetime,
) -> bool:
    count = await session.scalar(
        select(func.count())
        .select_from(MaintenanceWindow)
        .where(
            MaintenanceWindow.tenant_id == tenant_id,
            MaintenanceWindow.project_id == project_id,
            MaintenanceWindow.enabled.is_(True),
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at >= now,
            (MaintenanceWindow.asset_id.is_(None)) | (MaintenanceWindow.asset_id == asset_id),
        )
    )
    return (count or 0) > 0


def _verify_webhook_authorization(request: Request) -> None:
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else ""
    expected = get_settings().alertmanager_webhook_token.get_secret_value()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise ApplicationError(
            code="AIOPS_5000", message="Alertmanager Webhook 授权无效", status_code=401
        )


def _normalized_fingerprint(
    tenant_id: UUID, project_id: UUID, asset_id: UUID, labels: dict[str, str]
) -> str:
    stable_labels = {
        key: value
        for key, value in labels.items()
        if key not in {"severity", "prometheus", "replica"}
    }
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "asset_id": str(asset_id),
            "labels": stable_labels,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _normalize_severity(raw: str) -> str:
    value = raw.lower().strip()
    if value in {"critical", "fatal", "emergency", "high"}:
        return "critical"
    if value in {"warning", "warn", "medium"}:
        return "warning"
    return "info"


async def _evidence_refs(
    incoming: AlertmanagerAlert,
    verified_target: VerifiedTarget,
    backend: MetricsBackend,
) -> list[dict[str, Any]]:
    query = incoming.annotations.get("evidence_query") or "up" + target_selector(
        verified_target.target, verified_target.binding
    )
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    metric_evidence: dict[str, Any] = {
        "type": "prometheus_query",
        "query": query,
        "observed_at": observed_at,
        "source": get_settings().prometheus_url,
    }
    try:
        samples = await backend.instant_query(query)
        for sample in samples:
            require_sample_identity(sample, verified_target.target, verified_target.binding)
            require_sample_freshness(sample)
        metric_evidence["samples"] = [
            {
                "metric": sample.metric,
                "timestamp": sample.observed_at.isoformat(),
                "value": sample.value,
            }
            for sample in samples[:20]
        ]
        metric_evidence["status"] = "collected" if samples else "empty"
    except ApplicationError as exc:
        metric_evidence["status"] = "unavailable"
        metric_evidence["error_code"] = exc.code
    return [
        metric_evidence,
        {
            "type": "alertmanager_fingerprint",
            "value": incoming.fingerprint or "not-provided",
        },
    ]


def _resolved_end(incoming: AlertmanagerAlert, now: datetime) -> datetime | None:
    if incoming.status != "resolved":
        return None
    if incoming.endsAt is None or incoming.endsAt.year <= 1:
        return now
    return _as_utc(incoming.endsAt)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validated_window_range(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    normalized_start = _as_utc(starts_at)
    normalized_end = _as_utc(ends_at)
    if normalized_end <= normalized_start:
        raise ApplicationError(
            code="AIOPS_6103", message="维护窗口结束时间必须晚于开始时间", status_code=422
        )
    if normalized_end - normalized_start > timedelta(days=31):
        raise ApplicationError(
            code="AIOPS_6103", message="单个维护窗口不能超过 31 天", status_code=422
        )
    return normalized_start, normalized_end


def _human_id(prefix: str) -> str:
    now = datetime.now(UTC)
    entropy = uuid4().hex[:8].upper()
    return f"{prefix}-{now:%Y%m%d}-{entropy}"
