import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

HTTP_REQUESTS = Counter(
    "aiops_x_http_requests_total",
    "Total number of HTTP requests handled by the control plane.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "aiops_x_http_request_duration_seconds",
    "Control-plane HTTP request duration in seconds.",
    ("method", "route"),
)
AGENTS_ONLINE = Gauge("aiops_x_agents_online", "Online Edge Agents by tenant.", ("tenant_id",))
AUTOMATION_JOBS = Counter(
    "aiops_x_automation_jobs_total", "Automation jobs by terminal state.", ("status",)
)
AUTOMATION_DURATION = Histogram(
    "aiops_x_automation_job_duration_seconds", "Automation job execution latency."
)
ALERTS_INGESTED = Counter(
    "aiops_x_alerts_ingested_total", "Alertmanager alerts by ingest outcome.", ("outcome",)
)
DB_POOL_SIZE = Gauge("aiops_x_database_pool_size", "Configured SQLAlchemy pool size.")
DB_POOL_CHECKED_OUT = Gauge(
    "aiops_x_database_pool_checked_out", "Checked-out SQLAlchemy connections."
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started_at
            HTTP_REQUESTS.labels(request.method, "unmatched", 500).inc()
            HTTP_DURATION.labels(request.method, "unmatched").observe(duration)
            logger.exception(
                "http_request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration * 1000, 2),
                request_id=getattr(request.state, "request_id", "unknown"),
                trace_id=getattr(request.state, "trace_id", "unknown"),
            )
            raise
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(request.method, route_path, response.status_code).inc()
        duration = time.perf_counter() - started_at
        HTTP_DURATION.labels(request.method, route_path).observe(duration)
        if duration >= 1:
            logger.warning(
                "slow_http_request",
                method=request.method,
                route=route_path,
                status=response.status_code,
                duration_ms=round(duration * 1000, 2),
                request_id=getattr(request.state, "request_id", "unknown"),
                trace_id=getattr(request.state, "trace_id", "unknown"),
            )
        return response


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
