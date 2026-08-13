from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.tenant.contracts import ProjectScope, TenantScope
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant


async def get_project_in_tenant(
    session: AsyncSession, tenant_id: UUID, project_id: UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    if project is None:
        raise ApplicationError(code="AIOPS_3004", message="项目不存在", status_code=404)
    return project


async def require_project_scope(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> ProjectScope:
    project = await get_project_in_tenant(session, tenant_id, project_id)
    return _project_scope(project)


async def get_tenant_scope_by_id(session: AsyncSession, tenant_id: UUID) -> TenantScope:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ApplicationError(code="AIOPS_2004", message="租户不存在", status_code=404)
    return _tenant_scope(tenant)


async def find_tenant_scope_by_slug(
    session: AsyncSession, slug: str, *, active_only: bool = False
) -> TenantScope | None:
    filters = [Tenant.slug == slug.strip().lower()]
    if active_only:
        filters.append(Tenant.status == "active")
    tenant = await session.scalar(select(Tenant).where(*filters))
    return _tenant_scope(tenant) if tenant is not None else None


async def create_tenant_scope(session: AsyncSession, *, name: str, slug: str) -> TenantScope:
    tenant = Tenant(name=name.strip(), slug=slug.strip().lower(), status="active")
    session.add(tenant)
    await session.flush()
    return _tenant_scope(tenant)


async def require_project_ids(
    session: AsyncSession, *, tenant_id: UUID, project_ids: set[UUID]
) -> set[UUID]:
    if not project_ids:
        return set()
    valid = set(
        (
            await session.scalars(
                select(Project.id).where(
                    Project.tenant_id == tenant_id,
                    Project.id.in_(project_ids),
                )
            )
        ).all()
    )
    if valid != project_ids:
        raise ApplicationError(code="AIOPS_3004", message="项目不存在", status_code=404)
    return valid


async def resolve_project_scope(
    session: AsyncSession, *, tenant_slug: str, project_slug: str
) -> tuple[TenantScope, ProjectScope]:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        raise ApplicationError(code="AIOPS_5002", message="告警租户不存在", status_code=404)
    project = await session.scalar(
        select(Project).where(Project.tenant_id == tenant.id, Project.slug == project_slug)
    )
    if project is None:
        raise ApplicationError(code="AIOPS_5003", message="告警项目不存在", status_code=404)
    return _tenant_scope(tenant), _project_scope(project)


def _tenant_scope(tenant: Tenant) -> TenantScope:
    return TenantScope(id=tenant.id, slug=tenant.slug, status=tenant.status)


def _project_scope(project: Project) -> ProjectScope:
    return ProjectScope(
        id=project.id,
        tenant_id=project.tenant_id,
        slug=project.slug,
        status=project.status,
    )
