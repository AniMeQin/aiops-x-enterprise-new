import base64
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.identity.infrastructure.models import (
    ApiToken,
    GroupMembership,
    ProjectMembership,
    Role,
    User,
    UserRole,
)

PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,128}$")
bearer_scheme = HTTPBearer(auto_error=False)
_required_project_access: ContextVar[str] = ContextVar("required_project_access", default="viewer")


@dataclass(frozen=True)
class ProjectGrant:
    project_id: UUID
    access_levels: frozenset[str]
    environment_constraints: frozenset[str]
    asset_tag_constraints: frozenset[str]
    gxp_access: bool


@dataclass
class _ProjectGrantAccumulator:
    access_levels: set[str]
    environment_constraints: set[str]
    asset_tag_constraints: set[str]
    gxp_access: bool = False


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    email: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    is_bootstrap_admin: bool
    auth_type: str = "user"
    credential_id: UUID | None = None
    project_grants: tuple[ProjectGrant, ...] | None = None


def validate_password_strength(password: str) -> None:
    if not PASSWORD_PATTERN.fullmatch(password):
        raise ApplicationError(
            code="AIOPS_2101",
            message="密码至少 12 位，并包含大小写字母、数字和特殊字符",
            status_code=422,
        )


def hash_password(password: str) -> str:
    validate_password_strength(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + _b64encode(salt) + "$" + _b64encode(digest)


def verify_password(password: str, encoded: str | None) -> bool:
    if encoded is None:
        return False
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = _b64decode(digest_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt_text),
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def issue_access_token(user: User) -> tuple[str, datetime]:
    settings = get_settings()
    if user.tenant_id is None:
        raise RuntimeError("authenticated users must belong to a tenant")
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload: dict[str, object] = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "type": "access",
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = _b64encode(_json_bytes(header)) + "." + _b64encode(_json_bytes(payload))
    signature = hmac.new(
        settings.jwt_secret.get_secret_value().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return signing_input + "." + _b64encode(signature), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
        header = json.loads(_b64decode(encoded_header))
        payload = json.loads(_b64decode(encoded_payload))
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise ValueError
        if header.get("alg") != "HS256" or payload.get("type") != "access":
            raise ValueError
        signing_input = encoded_header + "." + encoded_payload
        expected_signature = hmac.new(
            get_settings().jwt_secret.get_secret_value().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, _b64decode(encoded_signature)):
            raise ValueError
        expires_at = int(payload["exp"])
        if expires_at <= int(datetime.now(UTC).timestamp()):
            raise ValueError
        UUID(str(payload["sub"]))
        UUID(str(payload["tenant_id"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise _unauthorized() from None
    return payload


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    if credentials.credentials.startswith("axt_"):
        return await _api_token_principal(session, credentials.credentials, request)
    payload = decode_access_token(credentials.credentials)
    user_id = UUID(str(payload["sub"]))
    tenant_id = UUID(str(payload["tenant_id"]))
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or user.tenant_id != tenant_id:
        raise _unauthorized()
    roles = (
        await session.scalars(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    ).all()
    permissions = {permission for role in roles for permission in role.permissions}
    if user.is_bootstrap_admin:
        permissions.add("*")
    principal = Principal(
        user_id=user.id,
        tenant_id=tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=tuple(sorted(role.name for role in roles)),
        permissions=frozenset(permissions),
        is_bootstrap_admin=user.is_bootstrap_admin,
        project_grants=await _project_grants_for_user(session, user.id, tenant_id),
    )
    # Authentication reads start SQLAlchemy's implicit transaction. Close that
    # read-only scope before a mutating endpoint opens its explicit transaction.
    await session.rollback()
    return principal


def ensure_project_scope(principal: Principal, project_id: UUID) -> None:
    if principal.project_grants is None or "*" in principal.permissions:
        return
    grant = next((item for item in principal.project_grants if item.project_id == project_id), None)
    if grant is None:
        raise ApplicationError(code="AIOPS_2003", message="当前账号无权访问该项目", status_code=403)
    required = _required_project_access.get()
    allowed_levels = {
        "viewer": {"viewer", "operator", "approver", "manager", "token"},
        "operator": {"operator", "manager", "token"},
        "approver": {"approver", "manager", "token"},
        "manager": {"manager", "token"},
    }
    if not grant.access_levels.intersection(allowed_levels[required]):
        raise ApplicationError(
            code="AIOPS_2003",
            message="当前账号的项目访问级别不足",
            status_code=403,
        )


def scoped_project_ids(principal: Principal) -> frozenset[UUID] | None:
    if principal.project_grants is None or "*" in principal.permissions:
        return None
    return frozenset(grant.project_id for grant in principal.project_grants)


def ensure_asset_scope(
    principal: Principal,
    *,
    project_id: UUID,
    environment: str,
    tags: list[str],
    gxp_classification: str,
) -> None:
    ensure_project_scope(principal, project_id)
    if principal.project_grants is None or "*" in principal.permissions:
        return
    grant = next((item for item in principal.project_grants if item.project_id == project_id), None)
    if grant is None:
        raise ApplicationError(code="AIOPS_2003", message="当前账号无权访问该资产", status_code=403)
    if grant.environment_constraints and environment not in grant.environment_constraints:
        raise ApplicationError(
            code="AIOPS_2003", message="资产环境超出当前账号授权范围", status_code=403
        )
    if grant.asset_tag_constraints and not grant.asset_tag_constraints.intersection(tags):
        raise ApplicationError(
            code="AIOPS_2003", message="资产标签超出当前账号授权范围", status_code=403
        )
    if gxp_classification == "gxp" and not grant.gxp_access:
        raise ApplicationError(
            code="AIOPS_2003", message="当前账号未获得 GxP 资产访问权限", status_code=403
        )


def asset_in_scope(
    principal: Principal,
    *,
    project_id: UUID,
    environment: str,
    tags: list[str],
    gxp_classification: str,
) -> bool:
    try:
        ensure_asset_scope(
            principal,
            project_id=project_id,
            environment=environment,
            tags=tags,
            gxp_classification=gxp_classification,
        )
    except ApplicationError:
        return False
    return True


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if "*" not in principal.permissions and permission not in principal.permissions:
            raise ApplicationError(
                code="AIOPS_2003",
                message="当前账号无权执行此操作",
                status_code=403,
            )
        _required_project_access.set(_access_for_permission(permission))
        return principal

    return dependency


def _unauthorized() -> ApplicationError:
    return ApplicationError(
        code="AIOPS_2001",
        message="身份凭据无效或已过期",
        status_code=401,
    )


async def _api_token_principal(
    session: AsyncSession, raw_token: str, request: Request
) -> Principal:
    now = datetime.now(UTC)
    api_token = await session.scalar(
        select(ApiToken).where(ApiToken.token_hash == token_hash(raw_token))
    )
    if (
        api_token is None
        or api_token.revoked_at is not None
        or _as_utc(api_token.expires_at) <= now
    ):
        raise _unauthorized()
    user = await session.scalar(
        select(User).where(
            User.id == api_token.created_by,
            User.tenant_id == api_token.tenant_id,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise _unauthorized()
    api_token.last_used_at = now
    await session.commit()
    grants = tuple(
        ProjectGrant(
            project_id=UUID(project_id),
            access_levels=frozenset({"token"}),
            environment_constraints=frozenset(),
            asset_tag_constraints=frozenset(),
            gxp_access="gxp:read" in api_token.permissions,
        )
        for project_id in api_token.project_ids
    )
    principal = Principal(
        user_id=user.id,
        tenant_id=api_token.tenant_id,
        email=user.email,
        display_name=api_token.name,
        roles=("api_token",),
        permissions=frozenset(api_token.permissions),
        is_bootstrap_admin=False,
        auth_type="api_token",
        credential_id=api_token.id,
        project_grants=grants,
    )
    # Import lazily to keep the identity/audit module boundary acyclic. Every
    # accepted API token use is persisted even if the target endpoint is read-only.
    from aiops_x_api.modules.audit.application import append_audit

    async with session.begin():
        await append_audit(
            session,
            request,
            action="identity.api_token.used",
            resource_type="api_token",
            outcome="success",
            principal=principal,
            resource_id=str(api_token.id),
            metadata={
                "token_id": api_token.token_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
    return principal


async def _project_grants_for_user(
    session: AsyncSession, user_id: UUID, tenant_id: UUID
) -> tuple[ProjectGrant, ...] | None:
    group_ids = (
        await session.scalars(
            select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)
        )
    ).all()
    memberships = (
        await session.scalars(
            select(ProjectMembership).where(
                ProjectMembership.tenant_id == tenant_id,
                (
                    (ProjectMembership.subject_type == "user")
                    & (ProjectMembership.subject_id == user_id)
                )
                | (
                    (ProjectMembership.subject_type == "group")
                    & (ProjectMembership.subject_id.in_(group_ids))
                ),
            )
        )
    ).all()
    if not memberships:
        return () if get_settings().abac_enforced else None
    aggregated: dict[UUID, _ProjectGrantAccumulator] = {}
    for membership in memberships:
        current = aggregated.setdefault(
            membership.project_id,
            _ProjectGrantAccumulator(set(), set(), set()),
        )
        current.access_levels.add(membership.access_level)
        current.environment_constraints.update(membership.environment_constraints)
        current.asset_tag_constraints.update(membership.asset_tag_constraints)
        current.gxp_access = current.gxp_access or membership.gxp_access
    return tuple(
        ProjectGrant(
            project_id=project_id,
            access_levels=frozenset(value.access_levels),
            environment_constraints=frozenset(value.environment_constraints),
            asset_tag_constraints=frozenset(value.asset_tag_constraints),
            gxp_access=value.gxp_access,
        )
        for project_id, value in sorted(aggregated.items(), key=lambda item: str(item[0]))
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _access_for_permission(permission: str) -> str:
    if permission in {"approval:decide", "change:approve"}:
        return "approver"
    if permission in {"identity:write", "project:write"}:
        return "manager"
    suffix = permission.rsplit(":", 1)[-1]
    if suffix in {
        "write",
        "create",
        "execute",
        "invoke",
        "ingest",
        "index",
        "evaluate",
        "analyze",
        "generate",
    }:
        return "operator"
    return "viewer"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
