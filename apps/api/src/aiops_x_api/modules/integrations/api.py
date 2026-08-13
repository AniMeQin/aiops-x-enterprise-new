import asyncio
from datetime import UTC, datetime
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.core.outbound_http import open_without_redirect, validate_outbound_url
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.integrations.infrastructure.models import Integration
from aiops_x_api.modules.integrations.schemas import (
    IntegrationCreate,
    IntegrationPage,
    IntegrationProbeResult,
    IntegrationResponse,
    IntegrationUpdate,
)
from aiops_x_api.modules.secret_provider.service import validate_credential_ref
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/integrations", tags=["integrations"])
PROBE_PATHS = {
    "prometheus": "/-/ready",
    "alertmanager": "/-/ready",
    "grafana": "/api/health",
    "loki": "/ready",
    "tempo": "/ready",
    "webhook": "",
}


@router.get("", response_model=IntegrationPage)
async def list_integrations(
    principal: Annotated[Principal, Depends(require_permission("integration:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    integration_type: Annotated[str | None, Query(max_length=64)] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> IntegrationPage:
    filters = [Integration.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Integration.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(Integration.project_id == project_id)
    if integration_type:
        filters.append(Integration.integration_type == integration_type)
    if enabled is not None:
        filters.append(Integration.enabled == enabled)
    total = await session.scalar(select(func.count()).select_from(Integration).where(*filters))
    rows = (
        await session.scalars(
            select(Integration)
            .where(*filters)
            .order_by(Integration.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return IntegrationPage(
        items=[_response(row) for row in rows], page=page, page_size=page_size, total=total or 0
    )


@router.post("", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("integration:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrationResponse:
    await asyncio.to_thread(validate_outbound_url, payload.endpoint, resolve=False)
    if payload.project_id is not None:
        ensure_project_scope(principal, payload.project_id)
    if payload.credential_ref is not None:
        validate_credential_ref(payload.credential_ref)
    async with session.begin():
        if payload.project_id is not None:
            await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        existing = await session.scalar(
            select(Integration.id).where(
                Integration.tenant_id == principal.tenant_id, Integration.slug == payload.slug
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_7102", message="集成标识已存在", status_code=409)
        integration = Integration(
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            health_status="unknown" if payload.enabled else "disabled",
            **payload.model_dump(),
        )
        session.add(integration)
        await session.flush()
        await append_audit(
            session,
            request,
            action="integration.created",
            resource_type="integration",
            outcome="success",
            principal=principal,
            project_id=integration.project_id,
            resource_id=str(integration.id),
            metadata={
                "type": integration.integration_type,
                "credential_ref_present": bool(integration.credential_ref),
            },
        )
    return _response(integration)


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("integration:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrationResponse:
    integration = await _get_integration(session, principal.tenant_id, integration_id)
    if integration.project_id is not None:
        ensure_project_scope(principal, integration.project_id)
    return _response(integration)


@router.patch("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: UUID,
    payload: IntegrationUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("integration:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrationResponse:
    async with session.begin():
        integration = await _get_integration(session, principal.tenant_id, integration_id)
        if integration.project_id is not None:
            ensure_project_scope(principal, integration.project_id)
        changes = payload.model_dump(exclude_unset=True)
        if payload.endpoint is not None:
            await asyncio.to_thread(validate_outbound_url, payload.endpoint, resolve=False)
        if payload.credential_ref is not None:
            validate_credential_ref(payload.credential_ref)
        for field, value in changes.items():
            setattr(integration, field, value)
        integration.config_version += 1
        integration.health_status = "unknown" if integration.enabled else "disabled"
        integration.sync_error = None
        await append_audit(
            session,
            request,
            action="integration.updated",
            resource_type="integration",
            outcome="success",
            principal=principal,
            project_id=integration.project_id,
            resource_id=str(integration.id),
            metadata={
                "changed_fields": sorted(changes),
                "config_version": integration.config_version,
            },
        )
        await session.flush()
        await session.refresh(integration)
    return _response(integration)


@router.post("/{integration_id}/probe", response_model=IntegrationProbeResult)
async def probe_integration(
    integration_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("integration:probe"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrationProbeResult:
    async with session.begin():
        integration = await _get_integration(session, principal.tenant_id, integration_id)
        if integration.project_id is not None:
            ensure_project_scope(principal, integration.project_id)
        integration_type = integration.integration_type
        endpoint = integration.endpoint
        is_enabled = integration.enabled
    checked_at = datetime.now(UTC)
    if not is_enabled:
        status, message = "disabled", "集成已停用"
    else:
        status, message = await asyncio.to_thread(_probe_endpoint, integration_type, endpoint)
    async with session.begin():
        integration = await _get_integration(session, principal.tenant_id, integration_id)
        integration.health_status = status
        integration.last_checked_at = checked_at
        integration.sync_error = None if status == "healthy" else message
        await append_audit(
            session,
            request,
            action="integration.probed",
            resource_type="integration",
            outcome="success" if status == "healthy" else "failure",
            principal=principal,
            project_id=integration.project_id,
            resource_id=str(integration.id),
            metadata={"health_status": status},
        )
    return IntegrationProbeResult(
        id=integration.id, health_status=status, checked_at=checked_at, message=message
    )


async def _get_integration(
    session: AsyncSession, tenant_id: UUID, integration_id: UUID
) -> Integration:
    integration = await session.scalar(
        select(Integration).where(
            Integration.id == integration_id, Integration.tenant_id == tenant_id
        )
    )
    if integration is None:
        raise ApplicationError(code="AIOPS_7104", message="集成不存在", status_code=404)
    return integration


def _response(integration: Integration) -> IntegrationResponse:
    return IntegrationResponse(
        id=integration.id,
        tenant_id=integration.tenant_id,
        project_id=integration.project_id,
        slug=integration.slug,
        name=integration.name,
        integration_type=integration.integration_type,
        endpoint=integration.endpoint,
        credential_configured=bool(integration.credential_ref),
        enabled=integration.enabled,
        health_status=integration.health_status,
        last_checked_at=integration.last_checked_at,
        last_sync_at=integration.last_sync_at,
        sync_error=integration.sync_error,
        config_version=integration.config_version,
        capabilities=integration.capabilities,
        configuration=integration.configuration,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


def _probe_endpoint(integration_type: str, endpoint: str) -> tuple[str, str]:
    target = endpoint.rstrip("/") + PROBE_PATHS.get(integration_type, "")
    try:
        validate_outbound_url(target)
    except ApplicationError as error:
        return "unhealthy", error.message
    request = UrlRequest(  # noqa: S310 -- endpoint scheme validated by the request schema
        target, method="GET", headers={"User-Agent": "AIOps-X-Integration-Probe/1"}
    )
    try:
        with open_without_redirect(request, timeout=5) as response:
            response.read(1024)
            if 200 <= response.status < 400:
                return "healthy", f"HTTP {response.status}"
            return "unhealthy", f"HTTP {response.status}"
    except HTTPError as error:
        return "unhealthy", f"HTTP {error.code}"
    except (TimeoutError, URLError, OSError):
        return "unhealthy", "连接失败或超时"
