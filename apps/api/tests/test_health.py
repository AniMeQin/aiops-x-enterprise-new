from aiops_x_api.core.rate_limit import RateLimitMiddleware
from aiops_x_api.core.request_context import _context_id
from aiops_x_api.main import _safe_validation_errors, app
from aiops_x_api.modules.system.api import _ai_provider_status
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient


def test_health_reports_real_service_version() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "aiops-x-api",
        "version": "0.1.0",
    }
    assert response.headers["x-request-id"]
    assert response.headers["x-trace-id"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_request_context_rejects_oversized_or_unsafe_client_ids() -> None:
    assert _context_id("request-123") == "request-123"
    assert _context_id("x" * 65) != "x" * 65
    assert _context_id("value\nforged") != "value\nforged"


def test_unknown_route_uses_safe_error_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/not-found")

    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "AIOPS_1004"
    assert body["request_id"] != "unknown"
    assert body["trace_id"] != "unknown"
    assert "path" not in body["details"]


def test_metrics_exposes_request_counter() -> None:
    with TestClient(app) as client:
        client.get("/health")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "aiops_x_http_requests_total" in response.text


def test_validation_errors_do_not_echo_sensitive_input() -> None:
    error = RequestValidationError(
        [
            {
                "type": "string_type",
                "loc": ("body", "password"),
                "msg": "Input should be a valid string",
                "input": "must-not-be-returned",
            }
        ]
    )

    safe_errors = _safe_validation_errors(error)

    assert safe_errors == [
        {
            "type": "string_type",
            "location": ["body", "password"],
            "message": "Input should be a valid string",
        }
    ]
    assert "must-not-be-returned" not in str(safe_errors)


def test_rate_limit_returns_safe_error_and_retry_headers() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(
        RateLimitMiddleware,
        redis_url="",
        api_limit=2,
        auth_limit=2,
    )

    @limited_app.get("/api/v1/example")
    async def example() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(limited_app) as client:
        assert client.get("/api/v1/example").status_code == 200
        assert client.get("/api/v1/example").status_code == 200
        blocked = client.get("/api/v1/example")

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "AIOPS_1008"
    assert blocked.headers["retry-after"] == "60"


async def test_ai_provider_status_fails_closed_when_engine_is_unreachable() -> None:
    configured, message, healthy = await _ai_provider_status("http://127.0.0.1:1/api/v1/ai/status")

    assert configured is False
    assert healthy is False
    assert message == "AI Engine 状态不可用"
