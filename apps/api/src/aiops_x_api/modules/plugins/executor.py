import asyncio
import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from aiops_x_plugin_sdk import PluginResult

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.core.outbound_http import open_without_redirect, validate_outbound_url
from aiops_x_api.modules.integrations.application import IntegrationConnection
from aiops_x_api.modules.plugins.infrastructure.models import PluginDefinition
from aiops_x_api.modules.secret_provider.service import get_secret_provider

MAX_PLUGIN_RESPONSE_BYTES = 4 * 1024 * 1024
SAFE_METHODS = {"GET", "POST"}
SENSITIVE_KEYS = {"password", "passwd", "token", "secret", "authorization", "api_key", "apikey"}
SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(password|passwd|token|api[_-]?key|secret|authorization)(\s*[:=]\s*)([^\s,;]+)"
)


async def invoke_http_json_plugin(
    *,
    plugin: PluginDefinition,
    connection: IntegrationConnection,
    capability: str,
    operation: str,
    parameters: dict[str, Any],
) -> PluginResult:
    if plugin.entrypoint != "aiops_x.plugins.http_json_v1":
        raise ApplicationError(code="AIOPS_8702", message="插件执行入口不受支持", status_code=422)
    if capability not in plugin.capabilities:
        raise ApplicationError(code="AIOPS_8703", message="插件不具备请求的能力", status_code=422)
    if capability == "action":
        raise ApplicationError(
            code="AIOPS_8704",
            message="动作插件必须通过 Runbook、策略和审批链路执行",
            status_code=403,
        )
    descriptor = _operation_descriptor(plugin, connection, capability, operation)
    method = str(descriptor.get("method", "GET")).upper()
    path = str(descriptor.get("path", ""))
    if method not in SAFE_METHODS or not path.startswith("/") or path.startswith("//"):
        raise ApplicationError(code="AIOPS_8705", message="插件操作定义无效", status_code=422)
    if get_settings().is_production and not connection.endpoint.startswith("https://"):
        raise ApplicationError(
            code="AIOPS_8706", message="生产环境插件端点必须使用 HTTPS", status_code=422
        )
    headers = {"Accept": "application/json", "User-Agent": "AIOps-X-Plugin/1"}
    if connection.credential_ref:
        secret = await get_secret_provider().read(connection.credential_ref)
        _apply_auth(headers, connection.configuration.get("auth"), secret)
    started_at = datetime.now(UTC)
    try:
        document, response_hash = await _json_request(
            method=method,
            url=connection.endpoint.rstrip("/") + path,
            headers=headers,
            parameters=parameters,
            timeout_seconds=plugin.timeout_seconds,
        )
    except ApplicationError as exc:
        finished_at = datetime.now(UTC)
        return PluginResult(
            success=False,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            evidence=[
                {
                    "evidence_type": "plugin_invocation_error",
                    "source_ref": f"integration://{connection.id}/{operation}",
                    "observed_at": finished_at.isoformat(),
                    "error_code": exc.code,
                }
            ],
            error_code=exc.code,
            error_message=exc.message,
            retryable=exc.status_code >= 500,
            sanitized_output={},
            metadata={"operation": operation, "capability": capability},
        )
    finished_at = datetime.now(UTC)
    sanitized = _redact(document)
    if isinstance(document.get("plugin_result"), dict):
        provider_result = dict(document["plugin_result"])
        provider_result["started_at"] = started_at
        provider_result["finished_at"] = finished_at
        provider_result["sanitized_output"] = _redact(provider_result.get("sanitized_output", {}))
        evidence = provider_result.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ApplicationError(
                code="AIOPS_8711",
                message="插件后端返回结果缺少可追溯证据",
                status_code=502,
            )
        provider_result["evidence"] = _redact(evidence)
        provider_result["metadata"] = _redact(provider_result.get("metadata", {}))
        if provider_result.get("error_message") is not None:
            provider_result["error_message"] = _redact(str(provider_result["error_message"]))[:500]
        provider_result.pop("raw_output", None)
        return PluginResult.model_validate(provider_result)
    return PluginResult(
        success=True,
        status="succeeded",
        started_at=started_at,
        finished_at=finished_at,
        evidence=[
            {
                "evidence_type": "plugin_response",
                "source_ref": f"integration://{connection.id}/{operation}",
                "content_hash": response_hash,
                "observed_at": finished_at.isoformat(),
            }
        ],
        sanitized_output=sanitized,
        metadata={
            "operation": operation,
            "capability": capability,
            "integration_type": connection.integration_type,
            "response_hash": response_hash,
        },
    )


def _operation_descriptor(
    plugin: PluginDefinition,
    connection: IntegrationConnection,
    capability: str,
    operation: str,
) -> dict[str, Any]:
    if capability == "health_check":
        return plugin.health_check
    operations = connection.configuration.get("operations")
    descriptor = operations.get(operation) if isinstance(operations, dict) else None
    if not isinstance(descriptor, dict):
        raise ApplicationError(code="AIOPS_8707", message="集成未配置该插件操作", status_code=422)
    return {str(key): value for key, value in descriptor.items()}


def _apply_auth(headers: dict[str, str], auth_config: Any, secret: dict[str, str]) -> None:
    if not isinstance(auth_config, dict):
        raise ApplicationError(code="AIOPS_8708", message="集成认证配置无效", status_code=422)
    kind = auth_config.get("kind")
    if kind == "bearer":
        key = str(auth_config.get("token_key", "token"))
        token = secret.get(key)
        if not token:
            raise ApplicationError(code="AIOPS_8709", message="凭据缺少令牌字段", status_code=422)
        headers["Authorization"] = f"Bearer {token}"
    elif kind == "basic":
        username = secret.get(str(auth_config.get("username_key", "username")))
        password = secret.get(str(auth_config.get("password_key", "password")))
        if not username or password is None:
            raise ApplicationError(
                code="AIOPS_8709", message="凭据缺少用户名或密码字段", status_code=422
            )
        value = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {value}"
    elif kind == "header":
        header_name = str(auth_config.get("header_name", ""))
        secret_key = str(auth_config.get("secret_key", "value"))
        if header_name.lower() not in {"x-api-key", "x-auth-token"} or secret_key not in secret:
            raise ApplicationError(code="AIOPS_8708", message="集成认证配置无效", status_code=422)
        headers[header_name] = secret[secret_key]
    else:
        raise ApplicationError(code="AIOPS_8708", message="集成认证配置无效", status_code=422)


async def _json_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    parameters: dict[str, Any],
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    def fetch() -> tuple[dict[str, Any], str]:
        request_url = url
        data = None
        request_headers = dict(headers)
        if method == "GET" and parameters:
            safe_params = {
                key: value
                for key, value in parameters.items()
                if isinstance(value, (str, int, float, bool))
            }
            request_url += "?" + urlencode(safe_params)
        elif method == "POST":
            data = json.dumps(parameters, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(request_url, data=data, method=method, headers=request_headers)  # noqa: S310
        validate_outbound_url(request_url)
        with open_without_redirect(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_PLUGIN_RESPONSE_BYTES + 1)
        if len(raw) > MAX_PLUGIN_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("response_not_object")
        return {str(key): value for key, value in document.items()}, hashlib.sha256(raw).hexdigest()

    try:
        return await asyncio.to_thread(fetch)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code="AIOPS_8710",
            message="插件后端调用失败",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_TEXT_PATTERN.sub(r"\1\2[REDACTED]", value)
    return value
