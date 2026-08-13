import ipaddress
import socket
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise HTTPError(req.full_url, code, "redirects are disabled", headers, fp)  # type: ignore[arg-type]


def validate_outbound_url(url: str, *, resolve: bool = True) -> None:
    settings = get_settings()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ApplicationError(code="AIOPS_7110", message="外部集成地址无效", status_code=422)
    if settings.is_production and parsed.scheme != "https":
        raise ApplicationError(
            code="AIOPS_7111", message="生产环境外部集成必须使用 HTTPS", status_code=422
        )
    if settings.is_production and not any(
        _host_matches(parsed.hostname, allowed) for allowed in settings.outbound_allowed_hosts
    ):
        raise ApplicationError(
            code="AIOPS_7112", message="外部集成地址不在生产出口允许列表", status_code=403
        )
    # Registry writes only persist configuration. Resolution is repeated at the
    # point of use so Compose-internal names can be registered from outside its
    # DNS namespace without weakening request-time SSRF protection.
    if not resolve:
        return
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        }
    except OSError as exc:
        raise ApplicationError(
            code="AIOPS_7113", message="外部集成地址无法解析", status_code=422
        ) from exc
    for text in addresses:
        address = ipaddress.ip_address(text)
        if (
            address.is_unspecified
            or address.is_loopback
            or address.is_multicast
            or address.is_link_local
            or address.is_reserved
            or str(address) == "169.254.169.254"
        ):
            raise ApplicationError(
                code="AIOPS_7112", message="外部集成地址命中禁止网络范围", status_code=403
            )


def open_without_redirect(request: Request, timeout: int) -> Any:
    return build_opener(NoRedirect).open(request, timeout=timeout)


def _host_matches(host: str, allowed: str) -> bool:
    normalized = allowed.strip().lower().rstrip(".")
    candidate = host.lower().rstrip(".")
    if normalized.startswith("*."):
        suffix = normalized[1:]
        return candidate.endswith(suffix) and candidate != suffix[1:]
    return candidate == normalized
