import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.infrastructure.models import AuthSession, Role, User, UserRole
from aiops_x_api.modules.identity.schemas import (
    BootstrapRequest,
    BootstrapStatus,
    LoginRequest,
    PrincipalResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    TokenResponse,
    UserCreate,
    UserSummary,
    UserUpdate,
)
from aiops_x_api.modules.identity.security import (
    Principal,
    generate_opaque_token,
    get_current_principal,
    hash_password,
    issue_access_token,
    require_permission,
    token_hash,
    verify_password,
)
from aiops_x_api.modules.tenant.application import (
    create_tenant_scope,
    find_tenant_scope_by_slug,
)

router = APIRouter(prefix="/auth", tags=["identity"])
REFRESH_COOKIE = "aiops_x_refresh"
DUMMY_PASSWORD_HASH = hash_password("Timing-Safe-Dummy1!")


@router.get("/bootstrap/status", response_model=BootstrapStatus)
async def bootstrap_status(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BootstrapStatus:
    user_count = await session.scalar(select(func.count()).select_from(User))
    return BootstrapStatus(required=(user_count or 0) == 0)


@router.post("/bootstrap", response_model=UserSummary, status_code=201)
async def bootstrap(
    payload: BootstrapRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    bootstrap_token: Annotated[str | None, Header(alias="X-Bootstrap-Token")] = None,
) -> UserSummary:
    settings = get_settings()
    supplied = bootstrap_token or ""
    expected = settings.bootstrap_token.get_secret_value()
    if not hmac.compare_digest(supplied, expected):
        raise ApplicationError(code="AIOPS_2003", message="Bootstrap 授权无效", status_code=403)

    async with session.begin():
        user_count = await session.scalar(select(func.count()).select_from(User))
        if (user_count or 0) != 0:
            raise ApplicationError(code="AIOPS_2102", message="平台已经完成初始化", status_code=409)
        tenant = await find_tenant_scope_by_slug(session, payload.tenant_slug)
        if tenant is None:
            tenant = await create_tenant_scope(
                session,
                name=payload.tenant_name,
                slug=payload.tenant_slug,
            )
        role = Role(
            tenant_id=tenant.id,
            name="platform_admin",
            description="平台 Bootstrap 管理员",
            permissions=["*"],
        )
        session.add(role)
        user = User(
            tenant_id=tenant.id,
            email=payload.email,
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
            is_active=True,
            is_bootstrap_admin=True,
        )
        session.add(user)
        await session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        await append_audit(
            session,
            request,
            action="identity.bootstrap.completed",
            resource_type="user",
            outcome="success",
            actor_type="user",
            actor_id=str(user.id),
            tenant_id=tenant.id,
            resource_id=str(user.id),
            metadata={"role": role.name},
        )
    return UserSummary.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    now = datetime.now(UTC)
    settings = get_settings()
    async with session.begin():
        tenant = await find_tenant_scope_by_slug(session, payload.tenant_slug)
        user = None
        if tenant is not None:
            user = await session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id,
                    func.lower(User.email) == payload.email,
                )
            )
        if user is None:
            verify_password(payload.password, DUMMY_PASSWORD_HASH)
            await append_audit(
                session,
                request,
                action="identity.login.failed",
                resource_type="session",
                outcome="failure",
                actor_id=payload.email,
                tenant_id=tenant.id if tenant is not None else None,
                metadata={"reason": "invalid_credentials"},
            )
            invalid_credentials = True
        elif (locked_until := _as_utc(user.locked_until)) is not None and locked_until > now:
            await append_audit(
                session,
                request,
                action="identity.login.failed",
                resource_type="session",
                outcome="blocked",
                actor_id=str(user.id),
                tenant_id=user.tenant_id,
                metadata={"reason": "account_locked"},
            )
            raise ApplicationError(
                code="AIOPS_2004", message="账号已临时锁定，请稍后重试", status_code=423
            )
        elif not user.is_active or not verify_password(payload.password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_failures:
                user.locked_until = now + timedelta(seconds=settings.login_lock_seconds)
            await append_audit(
                session,
                request,
                action="identity.login.failed",
                resource_type="session",
                outcome="failure",
                actor_id=str(user.id),
                tenant_id=user.tenant_id,
                metadata={"reason": "invalid_credentials"},
            )
            invalid_credentials = True
        else:
            invalid_credentials = False
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login_at = now
            refresh_token, csrf_token = generate_opaque_token(), generate_opaque_token()
            auth_session = AuthSession(
                user_id=user.id,
                family_id=uuid4(),
                refresh_token_hash=token_hash(refresh_token),
                csrf_token_hash=token_hash(csrf_token),
                user_agent=request.headers.get("user-agent", "")[:255],
                client_ip=_client_ip(request),
                expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            )
            session.add(auth_session)
            await append_audit(
                session,
                request,
                action="identity.login.succeeded",
                resource_type="session",
                outcome="success",
                actor_type="user",
                actor_id=str(user.id),
                tenant_id=user.tenant_id,
                resource_id=str(auth_session.id),
            )

    if invalid_credentials or user is None:
        raise ApplicationError(code="AIOPS_2001", message="租户、邮箱或密码错误", status_code=401)
    access_token, expires_at = issue_access_token(user)
    principal = await _principal_for_user(session, user)
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",  # noqa: S106 -- OAuth2 token type, not a credential.
        expires_at=expires_at,
        csrf_token=csrf_token,
        user=_principal_response(principal),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> TokenResponse:
    if refresh_token is None or csrf_token is None:
        raise _invalid_session()
    now = datetime.now(UTC)
    settings = get_settings()
    async with session.begin():
        current = await session.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(refresh_token))
        )
        if current is None:
            raise _invalid_session()
        if current.revoked_at is not None:
            await session.execute(
                update(AuthSession)
                .where(AuthSession.family_id == current.family_id)
                .values(revoked_at=now)
            )
            replay_detected = True
        else:
            replay_detected = False
        if replay_detected:
            await append_audit(
                session,
                request,
                action="identity.refresh.reuse_detected",
                resource_type="session",
                outcome="blocked",
                actor_type="user",
                actor_id=str(current.user_id),
                resource_id=str(current.id),
            )
        elif _required_utc(current.expires_at) <= now or not hmac.compare_digest(
            current.csrf_token_hash, token_hash(csrf_token)
        ):
            current.revoked_at = now
            raise _invalid_session()
        else:
            user = await session.scalar(select(User).where(User.id == current.user_id))
            if user is None or not user.is_active:
                current.revoked_at = now
                raise _invalid_session()
            current.revoked_at = now
            new_refresh, new_csrf = generate_opaque_token(), generate_opaque_token()
            replacement = AuthSession(
                user_id=user.id,
                family_id=current.family_id,
                refresh_token_hash=token_hash(new_refresh),
                csrf_token_hash=token_hash(new_csrf),
                user_agent=request.headers.get("user-agent", "")[:255],
                client_ip=_client_ip(request),
                expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            )
            session.add(replacement)
            await append_audit(
                session,
                request,
                action="identity.session.refreshed",
                resource_type="session",
                outcome="success",
                actor_type="user",
                actor_id=str(user.id),
                tenant_id=user.tenant_id,
                resource_id=str(replacement.id),
            )
    if replay_detected:
        response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
        raise _invalid_session()
    if user is None:
        raise _invalid_session()
    access_token, expires_at = issue_access_token(user)
    principal = await _principal_for_user(session, user)
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",  # noqa: S106 -- OAuth2 token type, not a credential.
        expires_at=expires_at,
        csrf_token=new_csrf,
        user=_principal_response(principal),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(get_current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    async with session.begin():
        if refresh_token is not None:
            auth_session = await session.scalar(
                select(AuthSession).where(
                    AuthSession.refresh_token_hash == token_hash(refresh_token),
                    AuthSession.user_id == principal.user_id,
                )
            )
            if auth_session is not None:
                if csrf_token is None or not hmac.compare_digest(
                    auth_session.csrf_token_hash, token_hash(csrf_token)
                ):
                    raise ApplicationError(
                        code="AIOPS_2005", message="CSRF 校验失败", status_code=403
                    )
                auth_session.revoked_at = datetime.now(UTC)
        await append_audit(
            session,
            request,
            action="identity.logout",
            resource_type="session",
            outcome="success",
            principal=principal,
        )
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


@router.get("/me", response_model=PrincipalResponse)
async def me(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> PrincipalResponse:
    return _principal_response(principal)


@router.get("/users", response_model=list[UserSummary])
async def list_users(
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[UserSummary]:
    users = (
        await session.scalars(
            select(User).where(User.tenant_id == principal.tenant_id).order_by(User.created_at)
        )
    ).all()
    return [await _user_summary(session, user) for user in users]


@router.post("/users", response_model=UserSummary, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserSummary:
    async with session.begin():
        existing = await session.scalar(
            select(User.id).where(
                User.tenant_id == principal.tenant_id, func.lower(User.email) == payload.email
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_2202", message="用户邮箱已存在", status_code=409)
        roles = await _roles_in_scope(session, principal, payload.role_ids)
        user = User(
            tenant_id=principal.tenant_id,
            email=payload.email,
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
            is_active=True,
            is_bootstrap_admin=False,
        )
        session.add(user)
        await session.flush()
        session.add_all(UserRole(user_id=user.id, role_id=role.id) for role in roles)
        await append_audit(
            session,
            request,
            action="identity.user.created",
            resource_type="user",
            outcome="success",
            principal=principal,
            resource_id=str(user.id),
            metadata={"role_ids": [str(role.id) for role in roles]},
        )
    return await _user_summary(session, user)


@router.patch("/users/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserSummary:
    async with session.begin():
        user = await session.scalar(
            select(User)
            .where(User.id == user_id, User.tenant_id == principal.tenant_id)
            .with_for_update()
        )
        if user is None:
            raise ApplicationError(code="AIOPS_2204", message="用户不存在", status_code=404)
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("is_active") is False and (
            user.id == principal.user_id or user.is_bootstrap_admin
        ):
            raise ApplicationError(
                code="AIOPS_2203", message="不能停用当前账号或 Bootstrap 管理员", status_code=409
            )
        if payload.display_name is not None:
            user.display_name = payload.display_name.strip()
        if payload.is_active is not None:
            user.is_active = payload.is_active
        assigned_roles: list[Role] | None = None
        if payload.role_ids is not None:
            assigned_roles = await _roles_in_scope(session, principal, payload.role_ids)
            await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
            session.add_all(UserRole(user_id=user.id, role_id=role.id) for role in assigned_roles)
        await append_audit(
            session,
            request,
            action="identity.user.updated",
            resource_type="user",
            outcome="success",
            principal=principal,
            resource_id=str(user.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(user)
    return await _user_summary(session, user)


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RoleResponse]:
    roles = (
        await session.scalars(
            select(Role).where(Role.tenant_id == principal.tenant_id).order_by(Role.name)
        )
    ).all()
    return [RoleResponse.model_validate(role) for role in roles]


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    payload: RoleCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleResponse:
    permissions = _validated_delegated_permissions(principal, payload.permissions)
    async with session.begin():
        existing = await session.scalar(
            select(Role.id).where(Role.tenant_id == principal.tenant_id, Role.name == payload.name)
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_2302", message="角色名称已存在", status_code=409)
        role = Role(
            tenant_id=principal.tenant_id,
            name=payload.name,
            description=payload.description.strip(),
            permissions=permissions,
        )
        session.add(role)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.role.created",
            resource_type="role",
            outcome="success",
            principal=principal,
            resource_id=str(role.id),
            metadata={"permissions": permissions},
        )
    return RoleResponse.model_validate(role)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RoleResponse:
    async with session.begin():
        role = await session.scalar(
            select(Role)
            .where(Role.id == role_id, Role.tenant_id == principal.tenant_id)
            .with_for_update()
        )
        if role is None:
            raise ApplicationError(code="AIOPS_2304", message="角色不存在", status_code=404)
        if role.name == "platform_admin":
            raise ApplicationError(
                code="AIOPS_2303", message="Bootstrap 管理员角色不可修改", status_code=409
            )
        changes = payload.model_dump(exclude_unset=True)
        if payload.description is not None:
            role.description = payload.description.strip()
        if payload.permissions is not None:
            role.permissions = _validated_delegated_permissions(principal, payload.permissions)
        await append_audit(
            session,
            request,
            action="identity.role.updated",
            resource_type="role",
            outcome="success",
            principal=principal,
            resource_id=str(role.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(role)
    return RoleResponse.model_validate(role)


async def _principal_for_user(session: AsyncSession, user: User) -> Principal:
    if user.tenant_id is None:
        raise RuntimeError("authenticated users must belong to a tenant")
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
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=tuple(sorted(role.name for role in roles)),
        permissions=frozenset(permissions),
        is_bootstrap_admin=user.is_bootstrap_admin,
    )


async def _user_summary(session: AsyncSession, user: User) -> UserSummary:
    role_names = (
        await session.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.name)
        )
    ).all()
    return UserSummary(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_bootstrap_admin=user.is_bootstrap_admin,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=list(role_names),
    )


async def _roles_in_scope(
    session: AsyncSession, principal: Principal, role_ids: list[UUID]
) -> list[Role]:
    unique_ids = set(role_ids)
    roles = (
        await session.scalars(
            select(Role).where(Role.tenant_id == principal.tenant_id, Role.id.in_(unique_ids))
        )
    ).all()
    if len(roles) != len(unique_ids):
        raise ApplicationError(
            code="AIOPS_2304", message="角色不存在或超出租户范围", status_code=404
        )
    for role in roles:
        _validated_delegated_permissions(principal, role.permissions)
    return list(roles)


def _validated_delegated_permissions(principal: Principal, permissions: list[str]) -> list[str]:
    normalized = sorted({permission.strip() for permission in permissions if permission.strip()})
    if "*" in normalized and not principal.is_bootstrap_admin:
        raise ApplicationError(code="AIOPS_2003", message="无权授予平台管理员权限", status_code=403)
    if "*" not in principal.permissions:
        outside_scope = sorted(set(normalized) - principal.permissions)
        if outside_scope:
            raise ApplicationError(
                code="AIOPS_2003",
                message="不能授予当前账号不具备的权限",
                status_code=403,
                details={"permissions": outside_scope},
            )
    return normalized


def _principal_response(principal: Principal) -> PrincipalResponse:
    return PrincipalResponse(
        id=principal.user_id,
        tenant_id=principal.tenant_id,
        email=principal.email,
        display_name=principal.display_name,
        roles=list(principal.roles),
        permissions=sorted(principal.permissions),
        is_bootstrap_admin=principal.is_bootstrap_admin,
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
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


def _client_ip(request: Request) -> str:
    return request.client.host[:64] if request.client is not None else "unknown"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _invalid_session() -> ApplicationError:
    return ApplicationError(code="AIOPS_2001", message="登录会话无效或已过期", status_code=401)
