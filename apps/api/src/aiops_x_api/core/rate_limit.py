import hashlib
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from aiops_x_api.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        redis_url: str | None = None,
        api_limit: int | None = None,
        auth_limit: int | None = None,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        settings = get_settings()
        self.api_limit = api_limit or settings.api_rate_limit_per_minute
        self.auth_limit = auth_limit or settings.auth_rate_limit_per_minute
        configured_url = (
            redis_url if redis_url is not None else settings.redis_url.get_secret_value()
        )
        self.redis = (
            Redis.from_url(
                configured_url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            if configured_url
            else None
        )
        self.fallback: dict[tuple[str, int], int] = defaultdict(int)
        self.redis_unavailable_until = 0.0

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)
        limit = self.auth_limit if request.url.path.startswith("/api/v1/auth/") else self.api_limit
        allowed, remaining = await self._allowed(request, limit)
        if not allowed:
            response: Response = JSONResponse(
                status_code=429,
                content={
                    "code": "AIOPS_1008",
                    "message": "请求过于频繁，请稍后重试",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", "unknown"),
                    "trace_id": getattr(request.state, "trace_id", "unknown"),
                },
            )
            response.headers["Retry-After"] = "60"
        else:
            response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(remaining, 0))
        return response

    async def _allowed(self, request: Request, limit: int) -> tuple[bool, int]:
        minute = int(time.time() // 60)
        subject = request.client.host if request.client is not None else "unknown"
        identity = hashlib.sha256(f"{subject}:{request.url.path}:{minute}".encode()).hexdigest()
        if self.redis is not None and time.monotonic() >= self.redis_unavailable_until:
            try:
                key = f"aiops-x:rate-limit:{identity}"
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, 65)
                return count <= limit, limit - count
            except RedisError:
                self.redis_unavailable_until = time.monotonic() + 5
        fallback_key = (identity, minute)
        self.fallback[fallback_key] += 1
        if len(self.fallback) > 4096:
            self.fallback = {
                key: value for key, value in self.fallback.items() if key[1] >= minute - 1
            }
        count = self.fallback[fallback_key]
        return count <= limit, limit - count
