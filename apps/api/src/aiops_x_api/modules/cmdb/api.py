from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.cmdb.infrastructure.models import Asset, AssetComponent, AssetRelation
from aiops_x_api.modules.cmdb.schemas import (
    AssetComponentCreate,
    AssetComponentPage,
    AssetComponentResponse,
    AssetCreate,
    AssetPage,
    AssetRelationCreate,
    AssetRelationPage,
    AssetRelationResponse,
    AssetResponse,
    AssetUpdate,
)
from aiops_x_api.modules.identity.security import (
    Principal,
    asset_in_scope,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.secret_provider.service import validate_credential_ref
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/assets", tags=["cmdb"])


def _asset_response(asset: Asset) -> AssetResponse:
    """Build a public asset representation without exposing the secret-store path."""
    fields = {
        field: getattr(asset, field)
        for field in AssetResponse.model_fields
        if field != "credential_configured"
    }
    fields["credential_configured"] = bool(asset.credential_ref)
    return AssetResponse.model_validate(fields)


@router.get("", response_model=AssetPage)
async def list_assets(
    principal: Annotated[Principal, Depends(require_permission("asset:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    asset_type: Annotated[str | None, Query(max_length=64)] = None,
    lifecycle_status: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=160)] = None,
) -> AssetPage:
    filters = [Asset.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Asset.project_id.in_(allowed_project_ids))
    if project_id is not None:
        filters.append(Asset.project_id == project_id)
    if asset_type:
        filters.append(Asset.asset_type == asset_type)
    if lifecycle_status:
        filters.append(Asset.lifecycle_status == lifecycle_status)
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(Asset.name.ilike(term), Asset.asset_id.ilike(term)))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
    if allowed_project_ids is not None:
        candidates = (
            await session.scalars(
                select(Asset).where(*filters).order_by(Asset.created_at.desc()).limit(5000)
            )
        ).all()
        visible = [
            asset
            for asset in candidates
            if asset_in_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        ]
        start = (page - 1) * page_size
        return AssetPage(
            items=[_asset_response(asset) for asset in visible[start : start + page_size]],
            page=page,
            page_size=page_size,
            total=len(visible),
        )
    total = await session.scalar(select(func.count()).select_from(Asset).where(*filters))
    assets = (
        await session.scalars(
            select(Asset)
            .where(*filters)
            .order_by(Asset.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AssetPage(
        items=[_asset_response(asset) for asset in assets],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(
    payload: AssetCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AssetResponse:
    ensure_project_scope(principal, payload.project_id)
    ensure_asset_scope(
        principal,
        project_id=payload.project_id,
        environment=payload.environment,
        tags=payload.tags,
        gxp_classification=payload.gxp_classification,
    )
    if payload.credential_ref is not None:
        validate_credential_ref(payload.credential_ref)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        existing = await session.scalar(
            select(Asset.id).where(
                Asset.tenant_id == principal.tenant_id,
                Asset.asset_id == payload.asset_id,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_3102", message="资产标识已存在", status_code=409)
        asset = Asset(
            tenant_id=principal.tenant_id,
            agent_status="not_installed",
            monitoring_status="not_configured",
            **payload.model_dump(),
        )
        session.add(asset)
        await session.flush()
        await append_audit(
            session,
            request,
            action="asset.created",
            resource_type="asset",
            outcome="success",
            principal=principal,
            project_id=asset.project_id,
            resource_id=str(asset.id),
            metadata={
                "asset_id": asset.asset_id,
                "credential_ref_present": asset.credential_ref is not None,
                "idempotency_key_present": idempotency_key is not None,
            },
        )
    return _asset_response(asset)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("asset:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetResponse:
    asset = await _get_asset(session, principal.tenant_id, asset_id)
    ensure_asset_scope(
        principal,
        project_id=asset.project_id,
        environment=asset.environment,
        tags=asset.tags,
        gxp_classification=asset.gxp_classification,
    )
    return _asset_response(asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetResponse:
    async with session.begin():
        asset = await _get_asset(session, principal.tenant_id, asset_id)
        ensure_asset_scope(
            principal,
            project_id=asset.project_id,
            environment=asset.environment,
            tags=asset.tags,
            gxp_classification=asset.gxp_classification,
        )
        changes = payload.model_dump(exclude_unset=True)
        if payload.credential_ref is not None:
            validate_credential_ref(payload.credential_ref)
        if changes.get("project_id") is not None:
            ensure_project_scope(principal, changes["project_id"])
            await get_project_in_tenant(session, principal.tenant_id, changes["project_id"])
        for field, value in changes.items():
            setattr(asset, field, value)
        await append_audit(
            session,
            request,
            action="asset.updated",
            resource_type="asset",
            outcome="success",
            principal=principal,
            project_id=asset.project_id,
            resource_id=str(asset.id),
            metadata={"changed_fields": sorted(changes)},
        )
        await session.flush()
        await session.refresh(asset)
    return _asset_response(asset)


@router.delete("/{asset_id}", status_code=204)
async def retire_asset(
    asset_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    async with session.begin():
        asset = await _get_asset(session, principal.tenant_id, asset_id)
        ensure_asset_scope(
            principal,
            project_id=asset.project_id,
            environment=asset.environment,
            tags=asset.tags,
            gxp_classification=asset.gxp_classification,
        )
        asset.lifecycle_status = "retired"
        asset.agent_status = "disabled"
        await append_audit(
            session,
            request,
            action="asset.retired",
            resource_type="asset",
            outcome="success",
            principal=principal,
            project_id=asset.project_id,
            resource_id=str(asset.id),
        )
    return Response(status_code=204)


@router.get("/{asset_id}/components", response_model=AssetComponentPage)
async def list_asset_components(
    asset_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("asset:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    component_type: Annotated[str | None, Query(max_length=32)] = None,
) -> AssetComponentPage:
    asset = await _get_asset(session, principal.tenant_id, asset_id)
    ensure_asset_scope(
        principal,
        project_id=asset.project_id,
        environment=asset.environment,
        tags=asset.tags,
        gxp_classification=asset.gxp_classification,
    )
    filters = [
        AssetComponent.tenant_id == principal.tenant_id,
        AssetComponent.asset_id == asset.id,
    ]
    if component_type is not None:
        filters.append(AssetComponent.component_type == component_type)
    total = await session.scalar(select(func.count()).select_from(AssetComponent).where(*filters))
    rows = (
        await session.scalars(
            select(AssetComponent)
            .where(*filters)
            .order_by(AssetComponent.component_type, AssetComponent.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AssetComponentPage(
        items=[AssetComponentResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/{asset_id}/components", response_model=AssetComponentResponse, status_code=201)
async def create_asset_component(
    asset_id: UUID,
    payload: AssetComponentCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetComponentResponse:
    async with session.begin():
        asset = await _get_asset(session, principal.tenant_id, asset_id)
        ensure_asset_scope(
            principal,
            project_id=asset.project_id,
            environment=asset.environment,
            tags=asset.tags,
            gxp_classification=asset.gxp_classification,
        )
        if payload.parent_component_id is not None:
            parent = await session.scalar(
                select(AssetComponent).where(
                    AssetComponent.id == payload.parent_component_id,
                    AssetComponent.tenant_id == principal.tenant_id,
                    AssetComponent.asset_id == asset.id,
                )
            )
            if parent is None:
                raise ApplicationError(
                    code="AIOPS_3115",
                    message="父组件不存在或不属于当前资产",
                    status_code=422,
                )
        component = AssetComponent(
            tenant_id=principal.tenant_id,
            project_id=asset.project_id,
            asset_id=asset.id,
            **payload.model_dump(),
        )
        try:
            async with session.begin_nested():
                session.add(component)
                await session.flush()
        except IntegrityError as error:
            raise ApplicationError(
                code="AIOPS_3116",
                message="资产组件标识已存在",
                status_code=409,
            ) from error
        await append_audit(
            session,
            request,
            action="asset.component.created",
            resource_type="asset_component",
            outcome="success",
            principal=principal,
            project_id=asset.project_id,
            resource_id=str(component.id),
            metadata={
                "asset_id": str(asset.id),
                "component_type": component.component_type,
                "source": component.source,
            },
        )
    return AssetComponentResponse.model_validate(component)


@router.get("/{asset_id}/relations", response_model=AssetRelationPage)
async def list_asset_relations(
    asset_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("asset:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    direction: Annotated[Literal["outgoing", "incoming", "both"], Query()] = "both",
    active_only: Annotated[bool, Query()] = True,
) -> AssetRelationPage:
    await _get_asset(session, principal.tenant_id, asset_id)
    direction_filter = (
        AssetRelation.source_asset_id == asset_id
        if direction == "outgoing"
        else AssetRelation.target_asset_id == asset_id
        if direction == "incoming"
        else or_(
            AssetRelation.source_asset_id == asset_id,
            AssetRelation.target_asset_id == asset_id,
        )
    )
    filters = [AssetRelation.tenant_id == principal.tenant_id, direction_filter]
    if active_only:
        now = datetime.now(UTC)
        filters.append(or_(AssetRelation.expires_at.is_(None), AssetRelation.expires_at > now))
    total = await session.scalar(select(func.count()).select_from(AssetRelation).where(*filters))
    relations = (
        await session.scalars(
            select(AssetRelation)
            .where(*filters)
            .order_by(AssetRelation.effective_at.desc(), AssetRelation.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AssetRelationPage(
        items=[AssetRelationResponse.model_validate(relation) for relation in relations],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/{asset_id}/relations", response_model=AssetRelationResponse, status_code=201)
async def create_asset_relation(
    asset_id: UUID,
    payload: AssetRelationCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetRelationResponse:
    if payload.target_asset_id == asset_id:
        raise ApplicationError(code="AIOPS_3110", message="资产不能与自身建立关系", status_code=422)
    async with session.begin():
        source_asset = await _get_asset(session, principal.tenant_id, asset_id)
        await _get_asset(session, principal.tenant_id, payload.target_asset_id)
        existing = await session.scalar(
            select(AssetRelation.id).where(
                AssetRelation.tenant_id == principal.tenant_id,
                AssetRelation.source_asset_id == asset_id,
                AssetRelation.target_asset_id == payload.target_asset_id,
                AssetRelation.relation_type == payload.relation_type,
            )
        )
        if existing is not None:
            raise ApplicationError(code="AIOPS_3111", message="资产关系已存在", status_code=409)
        relation = AssetRelation(
            tenant_id=principal.tenant_id,
            source_asset_id=asset_id,
            **payload.model_dump(),
        )
        session.add(relation)
        await session.flush()
        await append_audit(
            session,
            request,
            action="asset.relation.created",
            resource_type="asset_relation",
            outcome="success",
            principal=principal,
            project_id=source_asset.project_id,
            resource_id=str(relation.id),
            metadata={
                "source_asset_id": str(asset_id),
                "target_asset_id": str(payload.target_asset_id),
                "relation_type": payload.relation_type,
            },
        )
    return AssetRelationResponse.model_validate(relation)


@router.delete("/{asset_id}/relations/{relation_id}", status_code=204)
async def expire_asset_relation(
    asset_id: UUID,
    relation_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("asset:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    async with session.begin():
        source_asset = await _get_asset(session, principal.tenant_id, asset_id)
        relation = await session.scalar(
            select(AssetRelation).where(
                AssetRelation.id == relation_id,
                AssetRelation.tenant_id == principal.tenant_id,
                AssetRelation.source_asset_id == asset_id,
            )
        )
        if relation is None:
            raise ApplicationError(code="AIOPS_3114", message="资产关系不存在", status_code=404)
        relation.expires_at = datetime.now(UTC)
        await append_audit(
            session,
            request,
            action="asset.relation.expired",
            resource_type="asset_relation",
            outcome="success",
            principal=principal,
            project_id=source_asset.project_id,
            resource_id=str(relation.id),
        )
    return Response(status_code=204)


async def _get_asset(session: AsyncSession, tenant_id: UUID, asset_id: UUID) -> Asset:
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id)
    )
    if asset is None:
        raise ApplicationError(code="AIOPS_3104", message="资产不存在", status_code=404)
    return asset
