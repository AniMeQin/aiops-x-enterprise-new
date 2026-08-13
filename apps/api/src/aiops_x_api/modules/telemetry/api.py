import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import Principal, require_permission
from aiops_x_api.modules.telemetry.adapters import (
    backend_health_request,
    backend_json_request,
    utc_timestamp,
)
from aiops_x_api.modules.telemetry.schemas import (
    BackendStatus,
    LogEntry,
    LogSearchResponse,
    TelemetryStatusResponse,
    TraceDetailResponse,
    TraceSearchItem,
    TraceSearchResponse,
)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])
SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|api[_-]?key|secret|authorization)(\s*[:=]\s*)([^\s,;]+)"
)


@router.get("/status", response_model=TelemetryStatusResponse)
async def telemetry_status(
    _: Annotated[Principal, Depends(require_permission("telemetry:read"))],
) -> TelemetryStatusResponse:
    settings = get_settings()
    probes = [
        ("prometheus", settings.prometheus_url, "/-/ready"),
        ("loki", settings.loki_url, "/ready"),
        ("tempo", settings.tempo_url, "/ready"),
    ]
    statuses: list[BackendStatus] = []
    for name, url, path in probes:
        try:
            await backend_health_request(backend=name, base_url=url, path=path, timeout_seconds=3)
        except ApplicationError:
            statuses.append(
                BackendStatus(backend=name, status="unavailable", message=f"{name} 当前不可用")
            )
        else:
            statuses.append(BackendStatus(backend=name, status="available", message=f"{name} 可用"))
    return TelemetryStatusResponse(backends=statuses)


@router.get("/logs", response_model=LogSearchResponse)
async def search_logs(
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("logs:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    query: Annotated[str, Query(min_length=2, max_length=2000)],
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> LogSearchResponse:
    end_time = end or datetime.now(UTC)
    start_time = start or (end_time - timedelta(hours=1))
    if start_time >= end_time or end_time - start_time > timedelta(days=7):
        raise ApplicationError(
            code="AIOPS_8402", message="日志查询时间范围无效或超过 7 天", status_code=422
        )
    payload = await backend_json_request(
        backend="Loki",
        base_url=get_settings().loki_url,
        path="/loki/api/v1/query_range",
        parameters={
            "query": query,
            "start": int(start_time.timestamp() * 1_000_000_000),
            "end": int(end_time.timestamp() * 1_000_000_000),
            "limit": limit,
            "direction": "backward",
        },
    )
    entries = _parse_loki_entries(payload, limit)
    async with session.begin():
        await append_audit(
            session,
            request,
            action="telemetry.logs.queried",
            resource_type="log_query",
            outcome="success",
            principal=principal,
            metadata={
                "query_length": len(query),
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "result_count": len(entries),
            },
        )
    return LogSearchResponse(entries=entries, query=query, start=start_time, end=end_time)


@router.get("/traces", response_model=TraceSearchResponse)
async def search_traces(
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("traces:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    tags: Annotated[str | None, Query(max_length=1000)] = None,
    service_name: Annotated[str | None, Query(max_length=255)] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> TraceSearchResponse:
    end_time = end or datetime.now(UTC)
    start_time = start or (end_time - timedelta(hours=1))
    if start_time >= end_time or end_time - start_time > timedelta(days=7):
        raise ApplicationError(
            code="AIOPS_8403", message="链路查询时间范围无效或超过 7 天", status_code=422
        )
    tag_query = tags or ""
    if service_name:
        tag_query = f'{tag_query} resource.service.name="{service_name}"'.strip()
    payload = await backend_json_request(
        backend="Tempo",
        base_url=get_settings().tempo_url,
        path="/api/search",
        parameters={
            "tags": tag_query,
            "start": int(utc_timestamp(start_time)),
            "end": int(utc_timestamp(end_time)),
            "limit": limit,
        },
    )
    traces = _parse_tempo_search(payload)
    async with session.begin():
        await append_audit(
            session,
            request,
            action="telemetry.traces.queried",
            resource_type="trace_query",
            outcome="success",
            principal=principal,
            metadata={
                "tag_query_present": bool(tag_query),
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "result_count": len(traces),
            },
        )
    return TraceSearchResponse(traces=traces)


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(
    trace_id: Annotated[str, Path(min_length=16, max_length=64, pattern=r"^[a-fA-F0-9]+$")],
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("traces:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TraceDetailResponse:
    payload = await backend_json_request(
        backend="Tempo",
        base_url=get_settings().tempo_url,
        path=f"/api/traces/{trace_id}",
    )
    trace = _redact_object(payload)
    async with session.begin():
        await append_audit(
            session,
            request,
            action="telemetry.trace.read",
            resource_type="trace",
            outcome="success",
            principal=principal,
            resource_id=trace_id.lower(),
        )
    return TraceDetailResponse(trace_id=trace_id.lower(), trace=trace)


def _parse_loki_entries(payload: dict[str, Any], limit: int) -> list[LogEntry]:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise ApplicationError(
            code="AIOPS_8404", message="Loki 返回的数据结构无效", status_code=502
        )
    entries: list[LogEntry] = []
    for stream in data["result"]:
        if not isinstance(stream, dict):
            continue
        labels_raw = stream.get("stream")
        labels = (
            {str(key): _redact_text(str(value)) for key, value in labels_raw.items()}
            if isinstance(labels_raw, dict)
            else {}
        )
        values = stream.get("values")
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, list) or len(value) != 2:
                continue
            try:
                timestamp = datetime.fromtimestamp(int(value[0]) / 1_000_000_000, tz=UTC)
            except (TypeError, ValueError, OSError):
                continue
            entries.append(
                LogEntry(timestamp=timestamp, labels=labels, line=_redact_text(str(value[1])))
            )
            if len(entries) >= limit:
                return entries
    return entries


def _parse_tempo_search(payload: dict[str, Any]) -> list[TraceSearchItem]:
    raw = payload.get("traces")
    if not isinstance(raw, list):
        raise ApplicationError(
            code="AIOPS_8405", message="Tempo 返回的数据结构无效", status_code=502
        )
    traces: list[TraceSearchItem] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("traceID"), str):
            continue
        traces.append(
            TraceSearchItem(
                trace_id=item["traceID"],
                root_service_name=_optional_string(item.get("rootServiceName")),
                root_trace_name=_optional_string(item.get("rootTraceName")),
                start_time_unix_nano=_optional_string(item.get("startTimeUnixNano")),
                duration_ms=_optional_int(item.get("durationMs")),
                attributes=_redact_object(
                    item.get("spanSet") if isinstance(item.get("spanSet"), dict) else {}
                ),
            )
        )
    return traces


def _redact_text(value: str) -> str:
    return SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)


def _redact_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if _sensitive_key(str(key)) else _redact_object(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_object(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in ("password", "passwd", "token", "secret", "authorization", "api_key")
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
