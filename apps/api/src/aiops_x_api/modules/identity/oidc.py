import asyncio
import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.core.outbound_http import open_without_redirect, validate_outbound_url
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.enterprise_schemas import (
    OidcAuthorizationResponse,
    OidcStatus,
)
from aiops_x_api.modules.identity.infrastructure.models import (
    AuthSession,
    OidcAuthorizationState,
    OidcIdentity,
    Role,
    User,
    UserRole,
)
from aiops_x_api.modules.identity.security import generate_opaque_token, token_hash
from aiops_x_api.modules.tenant.infrastructure.models import Tenant

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])
OIDC_CSRF_COOKIE = "aiops_x_oidc_csrf"
REFRESH_COOKIE = "aiops_x_refresh"


@router.get("/status", response_model=OidcStatus)
async def oidc_status() -> OidcStatus:
    settings = get_settings()
    configured = _configured()
    return OidcStatus(
        enabled=configured,
        issuer=settings.oidc_issuer_url if configured else None,
        client_id=settings.oidc_client_id if configured else None,
        message="OIDC 已配置" if configured else "OIDC 未配置",
    )


@router.get("/authorize", response_model=OidcAuthorizationResponse)
async def oidc_authorize(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    tenant_slug: Annotated[str, Query(min_length=3, max_length=80)],
    redirect_after: Annotated[str, Query(max_length=512)] = "/",
) -> OidcAuthorizationResponse:
    _require_configured()
    if not redirect_after.startswith("/") or redirect_after.startswith("//"):
        raise ApplicationError(code="AIOPS_2801", message="登录后跳转地址无效", status_code=422)
    metadata = await _provider_metadata()
    tenant = await session.scalar(
        select(Tenant).where(Tenant.slug == tenant_slug.strip().lower(), Tenant.status == "active")
    )
    if tenant is None:
        raise ApplicationError(code="AIOPS_2001", message="租户不存在或已停用", status_code=401)
    await session.rollback()
    state = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(48)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    async with session.begin():
        session.add(
            OidcAuthorizationState(
                tenant_id=tenant.id,
                state_hash=token_hash(state),
                nonce_hash=token_hash(nonce),
                code_verifier=verifier,
                redirect_after=redirect_after,
                expires_at=expires_at,
            )
        )
        await append_audit(
            session,
            request,
            action="identity.oidc.authorization.started",
            resource_type="oidc_session",
            outcome="success",
            tenant_id=tenant.id,
            actor_type="anonymous",
            actor_id="oidc",
        )
    settings = get_settings()
    authorization_url = (
        str(metadata["authorization_endpoint"])
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": settings.oidc_client_id,
                "redirect_uri": settings.oidc_redirect_uri,
                "scope": settings.oidc_scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )
    return OidcAuthorizationResponse(authorization_url=authorization_url, expires_at=expires_at)


@router.get("/callback")
async def oidc_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: Annotated[str, Query(min_length=8, max_length=4096)],
    state: Annotated[str, Query(min_length=16, max_length=512)],
) -> RedirectResponse:
    _require_configured()
    now = datetime.now(UTC)
    async with session.begin():
        authorization = await session.scalar(
            select(OidcAuthorizationState)
            .where(OidcAuthorizationState.state_hash == token_hash(state))
            .with_for_update()
        )
        if (
            authorization is None
            or authorization.consumed_at is not None
            or _as_utc(authorization.expires_at) <= now
        ):
            raise ApplicationError(
                code="AIOPS_2802", message="OIDC 登录状态无效或已过期", status_code=401
            )
        authorization.consumed_at = now
        tenant_id = authorization.tenant_id
        verifier = authorization.code_verifier
        expected_nonce_hash = authorization.nonce_hash
        redirect_after = authorization.redirect_after
    metadata = await _provider_metadata()
    token_document = await _exchange_code(metadata, code, verifier)
    id_token = token_document.get("id_token")
    if not isinstance(id_token, str):
        raise ApplicationError(
            code="AIOPS_2803", message="OIDC Provider 未返回 ID Token", status_code=502
        )
    claims = await _validate_id_token(id_token, metadata, expected_nonce_hash)
    subject = str(claims["sub"])
    email = str(claims.get("email", "")).strip().lower()
    if not email or claims.get("email_verified") is False:
        raise ApplicationError(
            code="AIOPS_2804", message="OIDC 账号缺少已验证邮箱", status_code=403
        )
    issuer = get_settings().oidc_issuer_url.rstrip("/")
    refresh_token, csrf_token = generate_opaque_token(), generate_opaque_token()
    async with session.begin():
        identity = await session.scalar(
            select(OidcIdentity).where(
                OidcIdentity.tenant_id == tenant_id,
                OidcIdentity.issuer == issuer,
                OidcIdentity.subject == subject,
            )
        )
        user = (
            await session.scalar(select(User).where(User.id == identity.user_id))
            if identity
            else None
        )
        if user is None:
            user = await session.scalar(
                select(User).where(User.tenant_id == tenant_id, func.lower(User.email) == email)
            )
        if user is None and get_settings().oidc_auto_provision:
            user = User(
                tenant_id=tenant_id,
                email=email,
                display_name=str(claims.get("name") or email).strip()[:120],
                password_hash=None,
                is_active=True,
                is_bootstrap_admin=False,
            )
            session.add(user)
            await session.flush()
            roles = (
                await session.scalars(
                    select(Role).where(
                        Role.tenant_id == tenant_id,
                        Role.name.in_(get_settings().oidc_default_role_names),
                    )
                )
            ).all()
            session.add_all(UserRole(user_id=user.id, role_id=role.id) for role in roles)
        if user is None or not user.is_active:
            raise ApplicationError(
                code="AIOPS_2805", message="OIDC 账号未在当前租户中获得授权", status_code=403
            )
        if identity is None:
            identity = OidcIdentity(
                tenant_id=tenant_id,
                user_id=user.id,
                issuer=issuer,
                subject=subject,
                email=email,
            )
            session.add(identity)
        elif identity.user_id != user.id:
            raise ApplicationError(code="AIOPS_2806", message="OIDC 身份映射冲突", status_code=409)
        identity.email = email
        identity.last_login_at = now
        user.last_login_at = now
        auth_session = AuthSession(
            user_id=user.id,
            family_id=uuid4(),
            refresh_token_hash=token_hash(refresh_token),
            csrf_token_hash=token_hash(csrf_token),
            user_agent=request.headers.get("user-agent", "")[:255],
            client_ip=(request.client.host[:64] if request.client else "unknown"),
            expires_at=now + timedelta(seconds=get_settings().refresh_token_ttl_seconds),
        )
        session.add(auth_session)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.oidc.login.succeeded",
            resource_type="session",
            outcome="success",
            tenant_id=tenant_id,
            actor_type="user",
            actor_id=str(user.id),
            resource_id=str(auth_session.id),
            metadata={"issuer": issuer, "identity_id": str(identity.id)},
        )
    response = RedirectResponse(url=redirect_after, status_code=303)
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/api/v1/auth",
    )
    response.set_cookie(
        OIDC_CSRF_COOKIE,
        csrf_token,
        max_age=120,
        httponly=False,
        secure=settings.is_production,
        samesite="strict",
        path="/",
    )
    return response


async def _provider_metadata() -> dict[str, Any]:
    settings = get_settings()
    issuer = settings.oidc_issuer_url.rstrip("/")
    document = await _json_request("GET", issuer + "/.well-known/openid-configuration")
    if document.get("issuer") != issuer:
        raise ApplicationError(
            code="AIOPS_2807", message="OIDC Provider Issuer 校验失败", status_code=502
        )
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(key)
        if not isinstance(value, str) or (
            settings.is_production and not value.startswith("https://")
        ):
            raise ApplicationError(
                code="AIOPS_2808", message="OIDC Provider 元数据无效", status_code=502
            )
    return document


async def _exchange_code(metadata: dict[str, Any], code: str, verifier: str) -> dict[str, Any]:
    settings = get_settings()
    return await _json_request(
        "POST",
        str(metadata["token_endpoint"]),
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "client_id": settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret.get_secret_value(),
            "code_verifier": verifier,
        },
    )


async def _validate_id_token(
    token: str, metadata: dict[str, Any], expected_nonce_hash: str
) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_b64decode(header_part))
        claims = json.loads(_b64decode(payload_part))
        if (
            not isinstance(header, dict)
            or not isinstance(claims, dict)
            or header.get("alg") != "RS256"
        ):
            raise ValueError
        jwks = await _json_request("GET", str(metadata["jwks_uri"]))
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise ValueError
        key = next(
            item
            for item in keys
            if isinstance(item, dict)
            and item.get("kid") == header.get("kid")
            and item.get("kty") == "RSA"
        )
        modulus = int.from_bytes(_b64decode(str(key["n"])), "big")
        exponent = int.from_bytes(_b64decode(str(key["e"])), "big")
        public_key = rsa.RSAPublicNumbers(exponent, modulus).public_key()
        public_key.verify(
            _b64decode(signature_part),
            f"{header_part}.{payload_part}".encode("ascii"),
            padding.PKCS1v15(),
            SHA256(),
        )
        now = int(datetime.now(UTC).timestamp())
        issuer = get_settings().oidc_issuer_url.rstrip("/")
        audience = claims.get("aud")
        if isinstance(audience, str):
            audience_valid = audience == get_settings().oidc_client_id
        elif isinstance(audience, list):
            audience_valid = get_settings().oidc_client_id in audience
        else:
            audience_valid = False
        if (
            claims.get("iss") != issuer
            or not audience_valid
            or int(claims["exp"]) <= now
            or int(claims.get("iat", now + 1)) > now + 60
            or token_hash(str(claims.get("nonce", ""))) != expected_nonce_hash
            or not isinstance(claims.get("sub"), str)
        ):
            raise ValueError
    except (
        InvalidSignature,
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ApplicationError(
            code="AIOPS_2809", message="OIDC ID Token 校验失败", status_code=401
        ) from exc
    return {str(key): value for key, value in claims.items()}


async def _json_request(
    method: str, url: str, form: dict[str, str] | None = None
) -> dict[str, Any]:
    def fetch() -> dict[str, Any]:
        data = urlencode(form).encode() if form is not None else None
        request = UrlRequest(  # noqa: S310 -- URL is validated before opening
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        validate_outbound_url(url)
        with open_without_redirect(request, timeout=15) as response:
            document = json.loads(response.read(2 * 1024 * 1024))
        if not isinstance(document, dict):
            raise ValueError
        return {str(key): value for key, value in document.items()}

    try:
        return await asyncio.to_thread(fetch)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code="AIOPS_2810",
            message="OIDC Provider 暂时不可用",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc


def _configured() -> bool:
    settings = get_settings()
    return bool(
        settings.oidc_enabled
        and settings.oidc_issuer_url
        and settings.oidc_client_id
        and settings.oidc_client_secret.get_secret_value()
    )


def _require_configured() -> None:
    if not _configured():
        raise ApplicationError(code="AIOPS_2811", message="OIDC 未配置", status_code=503)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
