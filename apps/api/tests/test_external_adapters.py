from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import pytest
from aiops_x_api.core import outbound_http
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.reporting import storage
from aiops_x_api.modules.telemetry import adapters


class Response:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False
        self.released = False

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


def test_outbound_url_validation_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_ENVIRONMENT", "production")
    monkeypatch.setenv("AIOPS_OUTBOUND_ALLOWED_HOSTS", '["api.example.test","*.svc.test"]')
    get_settings.cache_clear()
    outbound_http.validate_outbound_url("https://api.example.test/v1", resolve=False)
    outbound_http.validate_outbound_url("https://node.svc.test/v1", resolve=False)
    with pytest.raises(ApplicationError, match="必须使用 HTTPS"):
        outbound_http.validate_outbound_url("http://api.example.test", resolve=False)
    with pytest.raises(ApplicationError, match="允许列表"):
        outbound_http.validate_outbound_url("https://evil.example.test", resolve=False)
    with pytest.raises(ApplicationError, match="地址无效"):
        outbound_http.validate_outbound_url("https://user@example.test", resolve=False)

    monkeypatch.setenv("AIOPS_ENVIRONMENT", "development")
    get_settings.cache_clear()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ApplicationError, match="禁止网络范围"):
        outbound_http.validate_outbound_url("https://localhost.example.test")

    def unresolved(*_: object) -> Any:
        raise OSError("unresolved")

    monkeypatch.setattr(socket, "getaddrinfo", unresolved)
    with pytest.raises(ApplicationError, match="无法解析"):
        outbound_http.validate_outbound_url("https://missing.example.test")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_report_storage_success_limits_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_REPORT_BUCKET", "test-reports")
    get_settings.cache_clear()

    class Client:
        def __init__(self) -> None:
            self.created = False
            self.upload: tuple[str, str, bytes, str] | None = None
            self.response = Response(b"report-content")

        def bucket_exists(self, _: str) -> bool:
            return False

        def make_bucket(self, _: str) -> None:
            self.created = True

        def put_object(
            self,
            bucket: str,
            object_name: str,
            stream: BytesIO,
            length: int,
            *,
            content_type: str,
        ) -> None:
            self.upload = (bucket, object_name, stream.read(length), content_type)

        def get_object(self, _: str, __: str) -> Response:
            return self.response

    client = Client()
    monkeypatch.setattr(storage, "_client", lambda: client)
    object_ref = await storage.put_report(
        object_name="live/report.json", content=b"{}", content_type="application/json"
    )
    assert object_ref == "s3://test-reports/live/report.json"
    assert client.created is True
    assert client.upload == (
        "test-reports",
        "live/report.json",
        b"{}",
        "application/json",
    )
    assert await storage.get_report(object_ref) == b"report-content"
    assert client.response.closed and client.response.released
    with pytest.raises(ApplicationError, match="引用无效"):
        await storage.get_report("s3://other/report.json")

    client.response = Response(b"too-large")
    with pytest.raises(ApplicationError) as large:
        await storage.get_report(object_ref, max_bytes=3)
    assert large.value.code == "AIOPS_8605"

    monkeypatch.setattr(storage, "_client", lambda: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(ApplicationError) as unavailable:
        await storage.put_report(
            object_name="down.json", content=b"{}", content_type="application/json"
        )
    assert unavailable.value.code == "AIOPS_8601"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telemetry_adapters_parse_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [Response(b"ready"), Response(json.dumps({"status": "success"}).encode())]
    monkeypatch.setattr(adapters, "urlopen", lambda *_args, **_kwargs: responses.pop(0))
    await adapters.backend_health_request(
        backend="Loki", base_url="http://loki:3100", path="/ready"
    )
    document = await adapters.backend_json_request(
        backend="Tempo",
        base_url="http://tempo:3200",
        path="/api/search",
        parameters={"limit": 5},
    )
    assert document == {"status": "success"}
    assert adapters.utc_timestamp(datetime(2026, 1, 1, tzinfo=UTC)) > 0

    monkeypatch.setattr(adapters, "urlopen", lambda *_args, **_kwargs: Response(b"[]"))
    with pytest.raises(ApplicationError) as invalid:
        await adapters.backend_json_request(
            backend="Tempo", base_url="http://tempo:3200", path="/api/search"
        )
    assert invalid.value.code == "AIOPS_8401"

    def unavailable(*_: object, **__: object) -> Any:
        raise OSError("down")

    monkeypatch.setattr(adapters, "urlopen", unavailable)
    with pytest.raises(ApplicationError, match="Loki"):
        await adapters.backend_health_request(
            backend="Loki", base_url="http://loki:3100", path="/ready"
        )
