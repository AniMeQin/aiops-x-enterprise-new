from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BackendStatus(BaseModel):
    backend: Literal["prometheus", "loki", "tempo"]
    status: Literal["available", "unavailable"]
    message: str


class TelemetryStatusResponse(BaseModel):
    backends: list[BackendStatus]


class LogEntry(BaseModel):
    timestamp: datetime
    labels: dict[str, str]
    line: str


class LogSearchResponse(BaseModel):
    entries: list[LogEntry]
    query: str
    start: datetime
    end: datetime
    source: Literal["loki"] = "loki"


class TraceSearchItem(BaseModel):
    trace_id: str
    root_service_name: str | None = None
    root_trace_name: str | None = None
    start_time_unix_nano: str | None = None
    duration_ms: int | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSearchResponse(BaseModel):
    traces: list[TraceSearchItem]
    source: Literal["tempo"] = "tempo"


class TraceDetailResponse(BaseModel):
    trace_id: str
    trace: dict[str, Any]
    source: Literal["tempo"] = "tempo"
