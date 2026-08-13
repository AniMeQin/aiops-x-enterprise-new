import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.identity import oidc
from aiops_x_api.modules.identity.security import token_hash
from aiops_x_api.modules.integrations.application import IntegrationConnection
from aiops_x_api.modules.plugins import executor
from aiops_x_api.modules.plugins.infrastructure.models import PluginDefinition
from aiops_x_api.modules.secret_provider import service as secrets_service
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _plugin(capabilities: list[str] | None = None) -> PluginDefinition:
    return PluginDefinition(
        id=uuid4(),
        tenant_id=uuid4(),
        plugin_id="aiops-x.test",
        name="Test Plugin",
        version="1.0.0",
        vendor="AIOps-X",
        description="test",
        capabilities=capabilities or ["query", "health_check"],
        supported_asset_types=["linux"],
        configuration_schema={},
        credential_types=[],
        required_permissions=["plugin:invoke"],
        risk_level="R0",
        timeout_seconds=5,
        retry_policy={"max_attempts": 1},
        idempotent=True,
        health_check={"method": "GET", "path": "/health"},
        entrypoint="aiops_x.plugins.http_json_v1",
        enabled=True,
        manifest_hash="a" * 64,
        created_by=uuid4(),
    )


def _connection(*, credential_ref: str | None = None) -> IntegrationConnection:
    return IntegrationConnection(
        id=uuid4(),
        tenant_id=uuid4(),
        project_id=uuid4(),
        integration_type="test",
        endpoint="https://integration.example.test",
        credential_ref=credential_ref,
        configuration={
            "operations": {"lookup": {"method": "POST", "path": "/api/query"}},
            "auth": {"kind": "bearer", "token_key": "token"},
        },
        capabilities=("query",),
    )


@pytest.mark.asyncio
async def test_plugin_executor_returns_traceable_redacted_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def json_request(**_: object) -> tuple[dict[str, object], str]:
        return {"status": "ok", "token": "must-not-leak", "nested": {"password": "x"}}, "b" * 64

    monkeypatch.setattr(executor, "_json_request", json_request)
    result = await executor.invoke_http_json_plugin(
        plugin=_plugin(),
        connection=_connection(),
        capability="query",
        operation="lookup",
        parameters={"asset": "linux-1"},
    )
    assert result.success is True
    assert result.evidence[0]["source_ref"].startswith("integration://")
    assert result.sanitized_output["token"] == "[REDACTED]"  # noqa: S105
    assert result.sanitized_output["nested"] == {"password": "[REDACTED]"}

    async def unavailable(**_: object) -> tuple[dict[str, object], str]:
        raise ApplicationError(code="AIOPS_TEST", message="unavailable", status_code=503)

    monkeypatch.setattr(executor, "_json_request", unavailable)
    failed = await executor.invoke_http_json_plugin(
        plugin=_plugin(),
        connection=_connection(),
        capability="health_check",
        operation="health",
        parameters={},
    )
    assert failed.success is False and failed.retryable is True
    assert failed.evidence[0]["error_code"] == "AIOPS_TEST"


@pytest.mark.asyncio
async def test_plugin_executor_rejects_unsafe_or_untraceable_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_evidence(**_: object) -> tuple[dict[str, object], str]:
        return {
            "plugin_result": {
                "success": True,
                "status": "succeeded",
                "evidence": [],
            }
        }, "c" * 64

    monkeypatch.setattr(executor, "_json_request", no_evidence)
    with pytest.raises(ApplicationError, match="缺少可追溯证据"):
        await executor.invoke_http_json_plugin(
            plugin=_plugin(),
            connection=_connection(),
            capability="query",
            operation="lookup",
            parameters={},
        )
    with pytest.raises(ApplicationError, match="动作插件"):
        await executor.invoke_http_json_plugin(
            plugin=_plugin(["action"]),
            connection=_connection(),
            capability="action",
            operation="execute",
            parameters={},
        )
    invalid_connection = _connection()
    invalid_connection.configuration["operations"] = {
        "lookup": {"method": "DELETE", "path": "//unsafe"}
    }
    with pytest.raises(ApplicationError, match="插件操作定义无效"):
        await executor.invoke_http_json_plugin(
            plugin=_plugin(),
            connection=invalid_connection,
            capability="query",
            operation="lookup",
            parameters={},
        )


def test_plugin_auth_strategies_are_scoped_and_validated() -> None:
    headers: dict[str, str] = {}
    executor._apply_auth(headers, {"kind": "bearer"}, {"token": "value"})
    assert headers["Authorization"] == "Bearer value"
    headers = {}
    executor._apply_auth(headers, {"kind": "basic"}, {"username": "user", "password": "pass"})
    assert base64.b64decode(headers["Authorization"].removeprefix("Basic ")) == b"user:pass"
    headers = {}
    executor._apply_auth(
        headers,
        {"kind": "header", "header_name": "X-API-Key", "secret_key": "key"},
        {"key": "value"},
    )
    assert headers["X-API-Key"] == "value"
    with pytest.raises(ApplicationError):
        executor._apply_auth({}, {"kind": "header", "header_name": "Authorization"}, {})


@pytest.mark.asyncio
async def test_environment_and_vault_secret_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AIOPS_SECRET_PROVIDER", "environment")
    monkeypatch.setenv("AIOPS_TEST_PLUGIN_SECRET", "ephemeral-value")
    get_settings.cache_clear()
    provider = secrets_service.get_secret_provider()
    assert await provider.read("secret://env/AIOPS_TEST_PLUGIN_SECRET") == {
        "value": "ephemeral-value"
    }
    assert (await provider.health()).available is True
    secrets_service.validate_credential_ref("secret://env/AIOPS_TEST_PLUGIN_SECRET")
    with pytest.raises(ApplicationError):
        await provider.read("secret://env/lowercase")
    with pytest.raises(ApplicationError):
        secrets_service.validate_credential_ref("vault://kv/wrong-provider")

    token_file = tmp_path / "vault-token"
    token_file.write_text("scoped-token", encoding="utf-8")
    token_file.chmod(0o600)
    assert secrets_service._read_token(str(token_file)) == "scoped-token"
    token_file.chmod(0o644)
    with pytest.raises(ApplicationError, match="身份凭据不可用"):
        secrets_service._read_token(str(token_file))
    assert secrets_service._vault_path("vault://kv/service/api", "kv") == (
        "/v1/kv/data/service/api"
    )
    with pytest.raises(ApplicationError):
        secrets_service._vault_path("vault://kv/../root", "kv")

    monkeypatch.setenv("AIOPS_SECRET_PROVIDER", "vault")
    monkeypatch.setenv("AIOPS_VAULT_TOKEN_FILE", str(token_file))
    token_file.chmod(0o600)
    get_settings.cache_clear()

    async def vault_json(path: str, token: str | None) -> dict[str, object]:
        assert token == "scoped-token"  # noqa: S105 -- ephemeral fixture value
        if path.endswith("lookup-self"):
            return {"data": {"id": "service"}}
        return {"data": {"data": {"username": "svc", "password": "transient"}}}

    monkeypatch.setattr(secrets_service, "_vault_json", vault_json)
    vault = secrets_service.VaultSecretProvider()
    assert await vault.read("vault://kv/service/api") == {
        "username": "svc",
        "password": "transient",
    }
    assert (await vault.health()).available is True
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_oidc_rs256_token_validation_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_OIDC_ENABLED", "true")
    monkeypatch.setenv("AIOPS_OIDC_ISSUER_URL", "https://id.example.test/realms/aiops")
    monkeypatch.setenv("AIOPS_OIDC_CLIENT_ID", "aiops-x")
    monkeypatch.setenv("AIOPS_OIDC_CLIENT_SECRET", "test-client-secret")
    get_settings.cache_clear()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    kid = "oidc-test-key"
    nonce = "nonce-value"
    now = int(datetime.now(UTC).timestamp())
    header = {"alg": "RS256", "kid": kid, "typ": "JWT"}
    claims = {
        "iss": "https://id.example.test/realms/aiops",
        "aud": ["account", "aiops-x"],
        "sub": "employee-1",
        "email": "employee@example.test",
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    }
    header_part = _b64_json(header)
    payload_part = _b64_json(claims)
    signature = private_key.sign(
        f"{header_part}.{payload_part}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    jwt = f"{header_part}.{payload_part}.{_b64(signature)}"
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": kid,
                "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
                "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }

    async def oidc_json(
        method: str, url: str, form: dict[str, str] | None = None
    ) -> dict[str, object]:
        assert method == "GET" and form is None
        if url.endswith("openid-configuration"):
            return {
                "issuer": "https://id.example.test/realms/aiops",
                "authorization_endpoint": "https://id.example.test/authorize",
                "token_endpoint": "https://id.example.test/token",
                "jwks_uri": "https://id.example.test/jwks",
            }
        return jwks

    monkeypatch.setattr(oidc, "_json_request", oidc_json)
    metadata = await oidc._provider_metadata()
    validated = await oidc._validate_id_token(jwt, metadata, token_hash(nonce))
    assert validated["sub"] == "employee-1"
    assert oidc._configured() is True
    with pytest.raises(ApplicationError, match="ID Token 校验失败"):
        await oidc._validate_id_token(jwt, metadata, token_hash("different"))
    get_settings.cache_clear()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64_json(value: dict[str, object]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())
