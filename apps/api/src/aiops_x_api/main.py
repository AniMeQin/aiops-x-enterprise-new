from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from aiops_x_api import __version__
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import database_is_ready, get_engine
from aiops_x_api.core.errors import ApplicationError, ErrorResponse
from aiops_x_api.core.logging import configure_logging
from aiops_x_api.core.observability import MetricsMiddleware, metrics_response
from aiops_x_api.core.rate_limit import RateLimitMiddleware
from aiops_x_api.core.request_context import RequestContextMiddleware
from aiops_x_api.core.security_headers import SecurityHeadersMiddleware
from aiops_x_api.core.telemetry import configure_fastapi_telemetry
from aiops_x_api.modules.agent_control.api import router as agent_router
from aiops_x_api.modules.ai_gateway.api import router as ai_gateway_router
from aiops_x_api.modules.audit.api import router as audit_router
from aiops_x_api.modules.automation.api import router as automation_router
from aiops_x_api.modules.change.api import router as change_router
from aiops_x_api.modules.cmdb.api import router as cmdb_router
from aiops_x_api.modules.evidence.api import router as evidence_router
from aiops_x_api.modules.identity.api import router as identity_router
from aiops_x_api.modules.identity.enterprise_api import router as identity_enterprise_router
from aiops_x_api.modules.identity.oidc import router as oidc_router
from aiops_x_api.modules.incident.api import router as incident_router
from aiops_x_api.modules.integrations.api import router as integrations_router
from aiops_x_api.modules.knowledge.api import router as knowledge_router
from aiops_x_api.modules.monitoring.api import router as monitoring_router
from aiops_x_api.modules.operations.api import router as operations_router
from aiops_x_api.modules.plugins.api import router as plugins_router
from aiops_x_api.modules.reliability.api import router as reliability_router
from aiops_x_api.modules.reporting.api import router as reporting_router
from aiops_x_api.modules.secret_provider.api import router as secret_provider_router
from aiops_x_api.modules.security_center.api import router as security_center_router
from aiops_x_api.modules.system.api import router as system_router
from aiops_x_api.modules.telemetry.api import router as telemetry_router
from aiops_x_api.modules.tenant.api import router as tenant_router
from aiops_x_api.modules.topology.api import router as topology_router

logger = structlog.get_logger()
STANDARD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Bad request",
        401: "Authentication required or invalid",
        403: "Permission or policy denied",
        404: "Resource not found",
        409: "State or uniqueness conflict",
        422: "Validation or scope failure",
        429: "Rate limit exceeded",
        500: "Sanitized internal service error",
        502: "Upstream response invalid",
        503: "Required dependency unavailable",
    }.items()
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("service_started", service="aiops-x-api", version=__version__)
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    logger.info("service_stopped", service="aiops-x-api")


def _error_payload(request: Request, code: str, message: str, details: object) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "trace_id": getattr(request.state, "trace_id", "unknown"),
    }


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    return [
        {
            "type": error.get("type", "validation_error"),
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid input"),
        }
        for error in exc.errors()
    ]


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    application = FastAPI(
        title="AIOps-X Enterprise API",
        version=__version__,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
        responses=STANDARD_ERROR_RESPONSES,
    )
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Bootstrap-Token",
            "X-CSRF-Token",
            "X-Request-ID",
            "X-Trace-ID",
        ],
    )

    @application.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.code, exc.message, exc.details),
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request,
                "AIOPS_1001",
                "请求参数校验失败",
                {"errors": _safe_validation_errors(exc)},
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, "AIOPS_1004", "请求的资源不存在", {}),
        )

    @application.get("/health", tags=["platform"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "aiops-x-api", "version": __version__}

    @application.get("/ready", tags=["platform"])
    async def ready() -> JSONResponse:
        ready_now = await database_is_ready()
        return JSONResponse(
            status_code=200 if ready_now else 503,
            content={
                "status": "ok" if ready_now else "unavailable",
                "service": "aiops-x-api",
                "version": __version__,
            },
        )

    application.add_api_route("/metrics", metrics_response, methods=["GET"], tags=["platform"])
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(identity_router, prefix="/api/v1")
    application.include_router(identity_enterprise_router, prefix="/api/v1")
    application.include_router(oidc_router, prefix="/api/v1")
    application.include_router(tenant_router, prefix="/api/v1")
    application.include_router(cmdb_router, prefix="/api/v1")
    application.include_router(audit_router, prefix="/api/v1")
    application.include_router(agent_router, prefix="/api/v1")
    application.include_router(operations_router, prefix="/api/v1")
    application.include_router(monitoring_router, prefix="/api/v1")
    application.include_router(automation_router, prefix="/api/v1")
    application.include_router(ai_gateway_router, prefix="/api/v1")
    application.include_router(integrations_router, prefix="/api/v1")
    application.include_router(evidence_router, prefix="/api/v1")
    application.include_router(incident_router, prefix="/api/v1")
    application.include_router(change_router, prefix="/api/v1")
    application.include_router(knowledge_router, prefix="/api/v1")
    application.include_router(telemetry_router, prefix="/api/v1")
    application.include_router(reliability_router, prefix="/api/v1")
    application.include_router(reporting_router, prefix="/api/v1")
    application.include_router(topology_router, prefix="/api/v1")
    application.include_router(secret_provider_router, prefix="/api/v1")
    application.include_router(plugins_router, prefix="/api/v1")
    application.include_router(security_center_router, prefix="/api/v1")
    configure_fastapi_telemetry(application)
    return application


app = create_app()
