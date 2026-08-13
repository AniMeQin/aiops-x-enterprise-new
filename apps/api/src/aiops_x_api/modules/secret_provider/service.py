import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
from urllib.request import Request, urlopen

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError


class SecretProvider(Protocol):
    async def read(self, credential_ref: str) -> dict[str, str]: ...

    async def health(self) -> "SecretProviderStatus": ...


@dataclass(frozen=True)
class SecretProviderStatus:
    provider: str
    available: bool
    message: str


class VaultSecretProvider:
    async def read(self, credential_ref: str) -> dict[str, str]:
        settings = get_settings()
        path = _vault_path(credential_ref, settings.vault_kv_mount)
        token = _read_token(settings.vault_token_file)
        document = await _vault_json(path, token)
        payload = document.get("data")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ApplicationError(
                code="AIOPS_2904", message="凭据引用不存在或格式无效", status_code=404
            )
        result = {str(key): str(value) for key, value in data.items() if value is not None}
        if not result:
            raise ApplicationError(code="AIOPS_2904", message="凭据引用不存在", status_code=404)
        return result

    async def health(self) -> SecretProviderStatus:
        try:
            settings = get_settings()
            token = _read_token(settings.vault_token_file)
            await _vault_json("/v1/auth/token/lookup-self", token=token)
        except ApplicationError:
            return SecretProviderStatus(
                provider="vault", available=False, message="Vault 当前不可用"
            )
        return SecretProviderStatus(provider="vault", available=True, message="Vault 可用")


class EnvironmentSecretProvider:
    async def read(self, credential_ref: str) -> dict[str, str]:
        if not credential_ref.startswith("secret://env/"):
            raise ApplicationError(code="AIOPS_2901", message="凭据引用格式无效", status_code=422)
        variable = credential_ref.removeprefix("secret://env/")
        if not variable or not variable.replace("_", "").isalnum() or not variable.isupper():
            raise ApplicationError(code="AIOPS_2901", message="凭据引用格式无效", status_code=422)
        value = os.getenv(variable)
        if value is None:
            raise ApplicationError(code="AIOPS_2904", message="凭据引用不存在", status_code=404)
        return {"value": value}

    async def health(self) -> SecretProviderStatus:
        return SecretProviderStatus(
            provider="environment", available=True, message="环境变量 Secret Provider 可用"
        )


def get_secret_provider() -> SecretProvider:
    provider = get_settings().secret_provider.strip().lower()
    if provider == "vault":
        return VaultSecretProvider()
    if provider == "environment" and not get_settings().is_production:
        return EnvironmentSecretProvider()
    raise ApplicationError(
        code="AIOPS_2902", message="Secret Provider 未配置或不受支持", status_code=503
    )


def validate_credential_ref(credential_ref: str) -> None:
    provider = get_settings().secret_provider.strip().lower()
    expected = "vault://" if provider == "vault" else "secret://env/"
    if not credential_ref.startswith(expected):
        raise ApplicationError(
            code="AIOPS_2901",
            message=f"当前 Secret Provider 要求使用 {expected} 凭据引用",
            status_code=422,
        )


def _vault_path(reference: str, mount: str) -> str:
    prefix = f"vault://{mount}/"
    if not reference.startswith(prefix):
        raise ApplicationError(code="AIOPS_2901", message="Vault 凭据引用格式无效", status_code=422)
    relative = reference.removeprefix(prefix).strip("/")
    if not relative or any(part in {".", ".."} for part in relative.split("/")):
        raise ApplicationError(code="AIOPS_2901", message="Vault 凭据引用格式无效", status_code=422)
    encoded = "/".join(quote(part, safe="-_.") for part in relative.split("/"))
    return f"/v1/{quote(mount, safe='-_')}/data/{encoded}"


def _read_token(path_text: str) -> str:
    try:
        path = Path(path_text)
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError
        return value
    except (OSError, ValueError) as exc:
        raise ApplicationError(
            code="AIOPS_2903", message="Vault 身份凭据不可用", status_code=503
        ) from exc


async def _vault_json(path: str, token: str | None) -> dict[str, Any]:
    settings = get_settings()
    url = settings.vault_addr.rstrip("/") + path

    def fetch() -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        if settings.vault_namespace:
            headers["X-Vault-Namespace"] = settings.vault_namespace
        request = Request(url, headers=headers)  # noqa: S310 -- configured internal Vault URL
        with urlopen(request, timeout=settings.vault_timeout_seconds) as response:  # noqa: S310
            document = json.loads(response.read(1024 * 1024))
        if not isinstance(document, dict):
            raise ValueError
        return {str(key): value for key, value in document.items()}

    try:
        return await asyncio.to_thread(fetch)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code="AIOPS_2905",
            message="Vault 服务暂时不可用",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc
