import asyncio
import json
from typing import Annotated
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from redis.exceptions import RedisError

from aiops_x_api import __version__
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import database_is_ready
from aiops_x_api.modules.identity.security import Principal, require_permission
from aiops_x_api.modules.system.schemas import DependencyStatus, SecuritySettings, SystemInfo

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info", response_model=SystemInfo)
async def get_system_info(
    _: Annotated[Principal, Depends(require_permission("system:read"))],
) -> SystemInfo:
    ready = await database_is_ready()
    settings = get_settings()
    (
        redis_ok,
        nats_ok,
        minio_ok,
        prometheus_ok,
        ai_engine_ok,
        ai_provider_status,
    ) = await asyncio.gather(
        _redis_ready(),
        _tcp_ready(settings.nats_url),
        _http_ready(
            ("https" if settings.minio_secure else "http")
            + "://"
            + settings.minio_endpoint
            + "/minio/health/live"
        ),
        _http_ready(settings.prometheus_url.rstrip("/") + "/-/ready"),
        _http_ready(settings.ai_engine_url.rstrip("/") + "/ready"),
        _ai_provider_status(settings.ai_engine_url.rstrip("/") + "/api/v1/ai/status"),
    )
    ai_configured, provider_message, provider_healthy = ai_provider_status
    provider_dependency_status = (
        "healthy"
        if ai_configured and provider_healthy
        else "not_configured"
        if provider_healthy and provider_message == "AI 服务未配置"
        else "unhealthy"
    )
    dependencies = [
        _dependency("PostgreSQL", ready, True),
        _dependency("Redis", redis_ok, True),
        _dependency("NATS", nats_ok, True),
        _dependency("MinIO", minio_ok, True),
        _dependency("Prometheus", prometheus_ok, True),
        _dependency("AI Engine", ai_engine_ok, False),
        DependencyStatus(
            name="AI Provider",
            status=provider_dependency_status,
            required=False,
            message=provider_message,
        ),
    ]
    return SystemInfo(
        service="aiops-x-api",
        version=__version__,
        environment=settings.environment,
        database="connected" if ready else "unavailable",
        ai=(
            "configured"
            if ai_configured and ai_engine_ok
            else "not_configured"
            if provider_dependency_status == "not_configured"
            else "unavailable"
        ),
        dependencies=dependencies,
        security=SecuritySettings(
            access_token_ttl_seconds=settings.access_token_ttl_seconds,
            refresh_token_ttl_seconds=settings.refresh_token_ttl_seconds,
            login_max_failures=settings.login_max_failures,
            login_lock_seconds=settings.login_lock_seconds,
            auth_rate_limit_per_minute=settings.auth_rate_limit_per_minute,
            api_rate_limit_per_minute=settings.api_rate_limit_per_minute,
            agent_certificate_ttl_hours=settings.agent_certificate_ttl_hours,
            abac_enforced=settings.abac_enforced,
        ),
    )


async def _redis_ready() -> bool:
    client = Redis.from_url(get_settings().redis_url.get_secret_value(), socket_timeout=2)
    try:
        return bool(await client.ping())
    except (OSError, RedisError, TimeoutError):
        return False
    finally:
        await client.aclose()


async def _tcp_ready(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or 4222
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, port), 2)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False


async def _http_ready(url: str) -> bool:
    def probe() -> bool:
        try:
            with urlopen(url, timeout=2) as response:  # noqa: S310 -- internal configured dependency
                response.read(1024)
                return bool(200 <= response.status < 400)
        except (OSError, TimeoutError):
            return False

    return await asyncio.to_thread(probe)


async def _ai_provider_status(url: str) -> tuple[bool, str, bool]:
    def probe() -> tuple[bool, str, bool]:
        try:
            with urlopen(url, timeout=2) as response:  # noqa: S310 -- internal dependency
                document = json.loads(response.read(64 * 1024))
            configured = bool(document.get("configured"))
            message = str(document.get("message") or "AI 服务未配置")
            return configured, message, bool(response.status == 200)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return False, "AI Engine 状态不可用", False

    return await asyncio.to_thread(probe)


def _dependency(name: str, healthy: bool, required: bool) -> DependencyStatus:
    return DependencyStatus(
        name=name,
        status="healthy" if healthy else "unhealthy",
        required=required,
        message="连接正常" if healthy else "连接失败",
    )
