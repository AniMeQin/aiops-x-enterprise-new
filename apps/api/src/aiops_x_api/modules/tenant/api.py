from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant
from aiops_x_api.modules.tenant.infrastructure.models import Project
from aiops_x_api.modules.tenant.schemas import (
    ProjectCreate,
    ProjectPage,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["tenant"])


@router.get("", response_model=ProjectPage)
async def list_projects(
    principal: Annotated[Principal, Depends(require_permission("project:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
) -> ProjectPage:
    filters = [Project.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Project.id.in_(allowed_project_ids))
    if status:
        filters.append(Project.status == status)
    if search:
        filters.append(Project.name.ilike(f"%{search.strip()}%"))
    total = await session.scalar(select(func.count()).select_from(Project).where(*filters))
    projects = (
        await session.scalars(
            select(Project)
            .where(*filters)
            .order_by(Project.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ProjectPage(
        items=[ProjectResponse.model_validate(project) for project in projects],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("project:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProjectResponse:
    async with session.begin():
        duplicate = await session.scalar(
            select(Project.id).where(
                Project.tenant_id == principal.tenant_id,
                Project.slug == payload.slug,
            )
        )
        if duplicate is not None:
            raise ApplicationError(code="AIOPS_3002", message="项目标识已存在", status_code=409)
        project = Project(
            tenant_id=principal.tenant_id,
            name=payload.name.strip(),
            slug=payload.slug,
            status="active",
        )
        session.add(project)
        await session.flush()
        await append_audit(
            session,
            request,
            action="project.created",
            resource_type="project",
            outcome="success",
            principal=principal,
            project_id=project.id,
            resource_id=str(project.id),
            metadata={"idempotency_key_present": idempotency_key is not None},
        )
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("project:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    ensure_project_scope(principal, project_id)
    project = await get_project_in_tenant(session, principal.tenant_id, project_id)
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("project:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    ensure_project_scope(principal, project_id)
    async with session.begin():
        project = await get_project_in_tenant(session, principal.tenant_id, project_id)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if value is not None:
                setattr(project, field, value.strip() if isinstance(value, str) else value)
        await append_audit(
            session,
            request,
            action="project.updated",
            resource_type="project",
            outcome="success",
            principal=principal,
            project_id=project.id,
            resource_id=str(project.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(project)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def archive_project(
    project_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("project:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    ensure_project_scope(principal, project_id)
    async with session.begin():
        project = await get_project_in_tenant(session, principal.tenant_id, project_id)
        project.status = "archived"
        await append_audit(
            session,
            request,
            action="project.archived",
            resource_type="project",
            outcome="success",
            principal=principal,
            project_id=project.id,
            resource_id=str(project.id),
        )
    return Response(status_code=204)
