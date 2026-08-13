from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class AcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    request_id: str | None
    raw_body: bytes


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10) -> None:
        normalized = base_url.rstrip("/") + "/"
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AcceptanceError("base URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise AcceptanceError("base URL must not contain credentials")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds
        self.access_token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] | None = None,
    ) -> ApiResponse:
        target = urljoin(self.base_url, path.lstrip("/"))
        body = None
        request_headers = {"Accept": "application/json"}
        if self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            request_headers.update(headers)
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(  # noqa: S310 - base URL is restricted to HTTP(S) above
            target,
            data=body,
            headers=request_headers,
            method=method,
        )
        status: int
        response_body: bytes
        request_id: str | None
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                status = response.status
                response_body = response.read(1024 * 1024)
                request_id = response.headers.get("X-Request-ID")
        except HTTPError as error:
            status = error.code
            response_body = error.read(1024 * 1024)
            request_id = error.headers.get("X-Request-ID")
        except (OSError, TimeoutError, URLError) as error:
            raise AcceptanceError(f"request failed: {method} {path}: {error}") from error

        decoded: Any = None
        if response_body:
            try:
                decoded = json.loads(response_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                decoded = response_body.decode(errors="replace")[:1000]
        accepted = expected if expected is not None else {200}
        if status not in accepted:
            safe_error = decoded
            if isinstance(decoded, dict):
                safe_error = {
                    key: value
                    for key, value in decoded.items()
                    if key not in {"access_token", "csrf_token", "token"}
                }
            raise AcceptanceError(f"unexpected HTTP {status} for {method} {path}: {safe_error!r}")
        return ApiResponse(
            status=status,
            body=decoded,
            request_id=request_id,
            raw_body=response_body,
        )

    def login(self, tenant_slug: str, email: str, password: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/api/v1/auth/login",
            payload={"tenant_slug": tenant_slug, "email": email, "password": password},
        )
        if not isinstance(response.body, dict) or not response.body.get("access_token"):
            raise AcceptanceError("login response did not contain an access token")
        self.access_token = str(response.body["access_token"])
        user = response.body.get("user")
        if not isinstance(user, dict):
            raise AcceptanceError("login response did not contain a user")
        return user


def require_secret_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise AcceptanceError(f"required secret environment variable is missing: {name}")
    return value


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    if path.exists():
        raise AcceptanceError(f"evidence file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_path = path.with_name(f".{path.name}.incoming-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, path)
        path.chmod(0o600)
    except Exception:
        if temporary_path.exists():
            temporary_path.rename(temporary_path.with_suffix(".failed"))
        raise


def wait_until(
    description: str,
    operation: Any,
    *,
    timeout_seconds: float,
    interval_seconds: float = 1,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = operation()
            if result:
                return result
        except Exception as error:  # noqa: BLE001 - retain final polling error
            last_error = error
        time.sleep(interval_seconds)
    suffix = f": {last_error}" if last_error else ""
    raise AcceptanceError(f"timed out waiting for {description}{suffix}")
