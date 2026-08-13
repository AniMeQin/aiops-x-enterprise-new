import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aiops_x_api.core.errors import ApplicationError

MAX_BACKEND_RESPONSE_BYTES = 4 * 1024 * 1024


async def backend_health_request(
    *, backend: str, base_url: str, path: str, timeout_seconds: int = 3
) -> None:
    url = base_url.rstrip("/") + path

    def fetch() -> None:
        request = Request(url, headers={"Accept": "text/plain"})  # noqa: S310
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            response.read(1024)

    try:
        await asyncio.to_thread(fetch)
    except (OSError, TimeoutError, ValueError) as exc:
        raise ApplicationError(
            code="AIOPS_8401",
            message=f"{backend} 遥测服务暂时不可用",
            status_code=503,
            details={"backend": backend, "reason": type(exc).__name__},
        ) from exc


async def backend_json_request(
    *,
    backend: str,
    base_url: str,
    path: str,
    parameters: dict[str, str | int | float] | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    query = urlencode(parameters or {})
    url = base_url.rstrip("/") + path + (f"?{query}" if query else "")

    def fetch() -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"})  # noqa: S310
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            raw = response.read(MAX_BACKEND_RESPONSE_BYTES + 1)
        if len(raw) > MAX_BACKEND_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("response_not_object")
        return {str(key): value for key, value in document.items()}

    try:
        return await asyncio.to_thread(fetch)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code="AIOPS_8401",
            message=f"{backend} 遥测服务暂时不可用",
            status_code=503,
            details={"backend": backend, "reason": type(exc).__name__},
        ) from exc


def utc_timestamp(value: datetime) -> float:
    return value.timestamp()
