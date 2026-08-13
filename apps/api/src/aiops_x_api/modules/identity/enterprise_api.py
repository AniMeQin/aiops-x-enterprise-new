import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.enterprise_schemas import (
    ApiTokenCreate,
    ApiTokenIssued,
    ApiTokenResponse,
    DepartmentCreate,
    DepartmentResponse,
    GroupCreate,
    GroupResponse,
    MembershipUpdate,
    ProjectMembershipCreate,
    ProjectMembershipResponse,
)
from aiops_x_api.modules.identity.infrastructure.models import (
    ApiToken,
    Department,
    GroupMembership,
    IdentityGroup,
    ProjectMembership,
    User,
    UserDepartment,
)
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    token_hash,
)
from aiops_x_api.modules.tenant.infrastructure.models import Project

router = APIRouter(prefix="/auth", tags=["identity-enterprise"])


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DepartmentResponse]:
    rows = (
        await session.scalars(
            select(Department)
            .where(Department.tenant_id == principal.tenant_id)
            .order_by(Department.name)
        )
    ).all()
    return [DepartmentResponse.model_validate(row) for row in rows]


@router.post("/departments", response_model=DepartmentResponse, status_code=201)
async def create_department(
    payload: DepartmentCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DepartmentResponse:
    async with session.begin():
        if payload.parent_id is not None:
            parent = await session.scalar(
                select(Department.id).where(
                    Department.id == payload.parent_id,
                    Department.tenant_id == principal.tenant_id,
                )
            )
            if parent is None:
                raise ApplicationError(code="AIOPS_2404", message="上级部门不存在", status_code=404)
        duplicate = await session.scalar(
            select(Department.id).where(
                Department.tenant_id == principal.tenant_id,
                func.lower(Department.name) == payload.name.strip().lower(),
            )
        )
        if duplicate is not None:
            raise ApplicationError(code="AIOPS_2402", message="部门名称已存在", status_code=409)
        department = Department(
            tenant_id=principal.tenant_id,
            parent_id=payload.parent_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
        )
        session.add(department)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.department.created",
            resource_type="department",
            outcome="success",
            principal=principal,
            resource_id=str(department.id),
        )
    return DepartmentResponse.model_validate(department)


@router.get("/groups", response_model=list[GroupResponse])
async def list_groups(
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[GroupResponse]:
    rows = (
        await session.scalars(
            select(IdentityGroup)
            .where(IdentityGroup.tenant_id == principal.tenant_id)
            .order_by(IdentityGroup.name)
        )
    ).all()
    return [GroupResponse.model_validate(row) for row in rows]


@router.post("/groups", response_model=GroupResponse, status_code=201)
async def create_group(
    payload: GroupCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    async with session.begin():
        if payload.department_id is not None:
            department = await session.scalar(
                select(Department.id).where(
                    Department.id == payload.department_id,
                    Department.tenant_id == principal.tenant_id,
                )
            )
            if department is None:
                raise ApplicationError(code="AIOPS_2404", message="部门不存在", status_code=404)
        duplicate = await session.scalar(
            select(IdentityGroup.id).where(
                IdentityGroup.tenant_id == principal.tenant_id,
                func.lower(IdentityGroup.name) == payload.name.strip().lower(),
            )
        )
        if duplicate is not None:
            raise ApplicationError(code="AIOPS_2502", message="用户组名称已存在", status_code=409)
        group = IdentityGroup(
            tenant_id=principal.tenant_id,
            department_id=payload.department_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
        )
        session.add(group)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.group.created",
            resource_type="identity_group",
            outcome="success",
            principal=principal,
            resource_id=str(group.id),
        )
    return GroupResponse.model_validate(group)


@router.put("/groups/{group_id}/members", status_code=204)
async def replace_group_members(
    group_id: UUID,
    payload: MembershipUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    unique_ids = set(payload.user_ids)
    async with session.begin():
        group = await session.scalar(
            select(IdentityGroup).where(
                IdentityGroup.id == group_id,
                IdentityGroup.tenant_id == principal.tenant_id,
            )
        )
        if group is None:
            raise ApplicationError(code="AIOPS_2504", message="用户组不存在", status_code=404)
        valid_ids = set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.tenant_id == principal.tenant_id, User.id.in_(unique_ids)
                    )
                )
            ).all()
        )
        if valid_ids != unique_ids:
            raise ApplicationError(
                code="AIOPS_2204", message="用户不存在或超出租户范围", status_code=404
            )
        await session.execute(delete(GroupMembership).where(GroupMembership.group_id == group.id))
        session.add_all(
            GroupMembership(group_id=group.id, user_id=user_id) for user_id in unique_ids
        )
        await append_audit(
            session,
            request,
            action="identity.group.members.replaced",
            resource_type="identity_group",
            outcome="success",
            principal=principal,
            resource_id=str(group.id),
            metadata={"member_count": len(unique_ids)},
        )
    return Response(status_code=204)


@router.get("/groups/{group_id}/members", response_model=list[UUID])
async def list_group_members(
    group_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[UUID]:
    group = await session.scalar(
        select(IdentityGroup.id).where(
            IdentityGroup.id == group_id,
            IdentityGroup.tenant_id == principal.tenant_id,
        )
    )
    if group is None:
        raise ApplicationError(code="AIOPS_2504", message="用户组不存在", status_code=404)
    return list(
        (
            await session.scalars(
                select(GroupMembership.user_id).where(GroupMembership.group_id == group_id)
            )
        ).all()
    )


@router.get("/departments/{department_id}/members", response_model=list[UUID])
async def list_department_members(
    department_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[UUID]:
    department = await session.scalar(
        select(Department.id).where(
            Department.id == department_id,
            Department.tenant_id == principal.tenant_id,
        )
    )
    if department is None:
        raise ApplicationError(code="AIOPS_2404", message="部门不存在", status_code=404)
    return list(
        (
            await session.scalars(
                select(UserDepartment.user_id).where(UserDepartment.department_id == department_id)
            )
        ).all()
    )


@router.put("/departments/{department_id}/members", status_code=204)
async def replace_department_members(
    department_id: UUID,
    payload: MembershipUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    unique_ids = set(payload.user_ids)
    async with session.begin():
        department = await session.scalar(
            select(Department).where(
                Department.id == department_id,
                Department.tenant_id == principal.tenant_id,
            )
        )
        if department is None:
            raise ApplicationError(code="AIOPS_2404", message="部门不存在", status_code=404)
        valid_ids = set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.tenant_id == principal.tenant_id,
                        User.id.in_(unique_ids),
                    )
                )
            ).all()
        )
        if valid_ids != unique_ids:
            raise ApplicationError(
                code="AIOPS_2204", message="用户不存在或超出租户范围", status_code=404
            )
        await session.execute(
            delete(UserDepartment).where(UserDepartment.department_id == department.id)
        )
        session.add_all(
            UserDepartment(department_id=department.id, user_id=user_id) for user_id in unique_ids
        )
        await append_audit(
            session,
            request,
            action="identity.department.members.replaced",
            resource_type="department",
            outcome="success",
            principal=principal,
            resource_id=str(department.id),
            metadata={"member_count": len(unique_ids)},
        )
    return Response(status_code=204)


@router.get("/project-memberships", response_model=list[ProjectMembershipResponse])
async def list_project_memberships(
    principal: Annotated[Principal, Depends(require_permission("identity:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectMembershipResponse]:
    rows = (
        await session.scalars(
            select(ProjectMembership)
            .where(ProjectMembership.tenant_id == principal.tenant_id)
            .order_by(ProjectMembership.created_at)
        )
    ).all()
    return [ProjectMembershipResponse.model_validate(row) for row in rows]


@router.post("/project-memberships", response_model=ProjectMembershipResponse, status_code=201)
async def create_project_membership(
    payload: ProjectMembershipCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectMembershipResponse:
    ensure_project_scope(principal, payload.project_id)
    async with session.begin():
        project = await session.scalar(
            select(Project.id).where(
                Project.id == payload.project_id,
                Project.tenant_id == principal.tenant_id,
            )
        )
        if project is None:
            raise ApplicationError(code="AIOPS_3004", message="项目不存在", status_code=404)
        subject_model = User if payload.subject_type == "user" else IdentityGroup
        subject = await session.scalar(
            select(subject_model.id).where(
                subject_model.id == payload.subject_id,
                subject_model.tenant_id == principal.tenant_id,
            )
        )
        if subject is None:
            raise ApplicationError(code="AIOPS_2604", message="授权主体不存在", status_code=404)
        existing = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.tenant_id == principal.tenant_id,
                ProjectMembership.project_id == payload.project_id,
                ProjectMembership.subject_type == payload.subject_type,
                ProjectMembership.subject_id == payload.subject_id,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_2602", message="项目授权已存在", status_code=409)
        membership = ProjectMembership(
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            **payload.model_dump(),
        )
        session.add(membership)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.project_scope.created",
            resource_type="project_membership",
            outcome="success",
            principal=principal,
            project_id=membership.project_id,
            resource_id=str(membership.id),
            metadata={
                "subject_type": membership.subject_type,
                "subject_id": str(membership.subject_id),
                "access_level": membership.access_level,
                "gxp_access": membership.gxp_access,
            },
        )
    return ProjectMembershipResponse.model_validate(membership)


@router.delete("/project-memberships/{membership_id}", status_code=204)
async def delete_project_membership(
    membership_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("identity:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    async with session.begin():
        membership = await session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.id == membership_id,
                ProjectMembership.tenant_id == principal.tenant_id,
            )
        )
        if membership is None:
            raise ApplicationError(code="AIOPS_2604", message="项目授权不存在", status_code=404)
        await append_audit(
            session,
            request,
            action="identity.project_scope.deleted",
            resource_type="project_membership",
            outcome="success",
            principal=principal,
            project_id=membership.project_id,
            resource_id=str(membership.id),
        )
        await session.delete(membership)
    return Response(status_code=204)


@router.get("/api-tokens", response_model=list[ApiTokenResponse])
async def list_api_tokens(
    principal: Annotated[Principal, Depends(require_permission("token:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ApiTokenResponse]:
    rows = (
        await session.scalars(
            select(ApiToken)
            .where(ApiToken.tenant_id == principal.tenant_id)
            .order_by(ApiToken.created_at.desc())
        )
    ).all()
    return [ApiTokenResponse.model_validate(row) for row in rows]


@router.post("/api-tokens", response_model=ApiTokenIssued, status_code=201)
async def create_api_token(
    payload: ApiTokenCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("token:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiTokenIssued:
    expires_at = _as_utc(payload.expires_at)
    now = datetime.now(UTC)
    if expires_at <= now or expires_at > now + timedelta(days=366):
        raise ApplicationError(
            code="AIOPS_2701",
            message="API Token 有效期必须介于当前时间和 366 天之间",
            status_code=422,
        )
    permissions = sorted(set(payload.permissions))
    if "*" in permissions:
        raise ApplicationError(
            code="AIOPS_2703", message="API Token 不允许万能权限", status_code=403
        )
    if "*" not in principal.permissions:
        outside_scope = set(permissions) - principal.permissions
        if outside_scope:
            raise ApplicationError(
                code="AIOPS_2003", message="不能授予当前账号不具备的权限", status_code=403
            )
    project_ids = set(payload.project_ids)
    for project_id in project_ids:
        ensure_project_scope(principal, project_id)
    raw_token = "axt_" + secrets.token_urlsafe(48)
    async with session.begin():
        valid_projects = set(
            (
                await session.scalars(
                    select(Project.id).where(
                        Project.tenant_id == principal.tenant_id,
                        Project.id.in_(project_ids),
                    )
                )
            ).all()
        )
        if valid_projects != project_ids:
            raise ApplicationError(code="AIOPS_3004", message="项目不存在", status_code=404)
        token = ApiToken(
            token_id=f"TOK-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}",
            tenant_id=principal.tenant_id,
            name=payload.name.strip(),
            token_prefix=raw_token[:12],
            token_hash=token_hash(raw_token),
            permissions=permissions,
            project_ids=sorted(str(project_id) for project_id in project_ids),
            created_by=principal.user_id,
            expires_at=expires_at,
        )
        session.add(token)
        await session.flush()
        await append_audit(
            session,
            request,
            action="identity.api_token.created",
            resource_type="api_token",
            outcome="success",
            principal=principal,
            resource_id=str(token.id),
            metadata={
                "token_id": token.token_id,
                "permissions": token.permissions,
                "project_ids": token.project_ids,
                "expires_at": expires_at.isoformat(),
            },
        )
    public = ApiTokenResponse.model_validate(token)
    return ApiTokenIssued(**public.model_dump(), token=raw_token)


@router.delete("/api-tokens/{token_id}", status_code=204)
async def revoke_api_token(
    token_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("token:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    async with session.begin():
        token = await session.scalar(
            select(ApiToken)
            .where(ApiToken.id == token_id, ApiToken.tenant_id == principal.tenant_id)
            .with_for_update()
        )
        if token is None:
            raise ApplicationError(code="AIOPS_2704", message="API Token 不存在", status_code=404)
        token.revoked_at = datetime.now(UTC)
        await append_audit(
            session,
            request,
            action="identity.api_token.revoked",
            resource_type="api_token",
            outcome="success",
            principal=principal,
            resource_id=str(token.id),
            metadata={"token_id": token.token_id},
        )
    return Response(status_code=204)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
