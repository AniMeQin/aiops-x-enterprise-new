import hashlib
import json
from typing import Annotated
from uuid import UUID

from aiops_x_plugin_sdk import PluginManifest
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
)
from aiops_x_api.modules.integrations.application import get_integration_connection
from aiops_x_api.modules.plugins.builtins import BUILTIN_MANIFESTS
from aiops_x_api.modules.plugins.executor import invoke_http_json_plugin
from aiops_x_api.modules.plugins.infrastructure.models import PluginDefinition, PluginInvocation
from aiops_x_api.modules.plugins.schemas import (
    BuiltinPluginResult,
    PluginDefinitionResponse,
    PluginInvocationRequest,
    PluginInvocationResponse,
    PluginRegister,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])
ALLOWED_ENTRYPOINTS = {"aiops_x.plugins.http_json_v1"}


@router.get("", response_model=list[PluginDefinitionResponse])
async def list_plugins(
    principal: Annotated[Principal, Depends(require_permission("plugin:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    enabled: Annotated[bool | None, Query()] = None,
) -> list[PluginDefinitionResponse]:
    filters = [PluginDefinition.tenant_id == principal.tenant_id]
    if enabled is not None:
        filters.append(PluginDefinition.enabled == enabled)
    rows = (
        await session.scalars(
            select(PluginDefinition)
            .where(*filters)
            .order_by(PluginDefinition.plugin_id, PluginDefinition.version.desc())
        )
    ).all()
    return [PluginDefinitionResponse.model_validate(row) for row in rows]


@router.post("", response_model=PluginDefinitionResponse, status_code=201)
async def register_plugin(
    payload: PluginRegister,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("plugin:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PluginDefinitionResponse:
    async with session.begin():
        row, created = await _register_manifest(
            session, principal=principal, manifest=payload.manifest, enabled=payload.enabled
        )
        if not created:
            raise ApplicationError(code="AIOPS_8701", message="插件版本已注册", status_code=409)
        await append_audit(
            session,
            request,
            action="plugin.registered",
            resource_type="plugin_definition",
            outcome="success",
            principal=principal,
            resource_id=str(row.id),
            metadata={
                "plugin_id": row.plugin_id,
                "version": row.version,
                "manifest_hash": row.manifest_hash,
            },
        )
    return PluginDefinitionResponse.model_validate(row)


@router.post("/builtins", response_model=BuiltinPluginResult)
async def register_builtin_plugins(
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("plugin:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BuiltinPluginResult:
    registered: list[PluginDefinitionResponse] = []
    unchanged: list[str] = []
    async with session.begin():
        for raw_manifest in BUILTIN_MANIFESTS:
            manifest = PluginManifest.model_validate(raw_manifest)
            row, created = await _register_manifest(
                session, principal=principal, manifest=manifest, enabled=True
            )
            if created:
                registered.append(PluginDefinitionResponse.model_validate(row))
            else:
                unchanged.append(f"{manifest.plugin_id}@{manifest.version}")
        await append_audit(
            session,
            request,
            action="plugin.builtins.synchronized",
            resource_type="plugin_registry",
            outcome="success",
            principal=principal,
            metadata={"registered": len(registered), "unchanged": len(unchanged)},
        )
    return BuiltinPluginResult(registered=registered, unchanged=unchanged)


@router.post("/{definition_id}/invoke", response_model=PluginInvocationResponse)
async def invoke_plugin(
    definition_id: UUID,
    payload: PluginInvocationRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("plugin:invoke"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PluginInvocationResponse:
    plugin = await session.scalar(
        select(PluginDefinition).where(
            PluginDefinition.id == definition_id,
            PluginDefinition.tenant_id == principal.tenant_id,
            PluginDefinition.enabled.is_(True),
        )
    )
    if plugin is None:
        raise ApplicationError(code="AIOPS_8700", message="插件不存在或已停用", status_code=404)
    for permission in plugin.required_permissions:
        if "*" not in principal.permissions and permission not in principal.permissions:
            raise ApplicationError(
                code="AIOPS_2003", message="当前账号缺少插件所需权限", status_code=403
            )
    connection = await get_integration_connection(
        session, tenant_id=principal.tenant_id, integration_id=payload.integration_id
    )
    project_id = payload.project_id or connection.project_id
    if project_id is not None:
        ensure_project_scope(principal, project_id)
    if connection.project_id is not None and project_id != connection.project_id:
        raise ApplicationError(
            code="AIOPS_8711", message="插件调用超出集成项目范围", status_code=403
        )
    if payload.asset_id is not None:
        asset = await get_asset_for_scope(
            session, tenant_id=principal.tenant_id, asset_id=payload.asset_id
        )
        if project_id is not None and asset.project_id != project_id:
            raise ApplicationError(
                code="AIOPS_8711", message="插件调用的资产超出项目范围", status_code=403
            )
        ensure_asset_scope(
            principal,
            project_id=asset.project_id,
            environment=asset.environment,
            tags=asset.tags,
            gxp_classification=asset.gxp_classification,
        )
    result = await invoke_http_json_plugin(
        plugin=plugin,
        connection=connection,
        capability=payload.capability,
        operation=payload.operation,
        parameters=payload.parameters,
    )
    await session.rollback()
    async with session.begin():
        invocation = PluginInvocation(
            tenant_id=principal.tenant_id,
            project_id=project_id,
            plugin_definition_id=plugin.id,
            integration_id=connection.id,
            asset_id=payload.asset_id,
            capability=payload.capability,
            operation=payload.operation,
            status=result.status,
            evidence=result.evidence,
            sanitized_output=result.sanitized_output,
            raw_output_ref=result.raw_output_ref,
            error_code=result.error_code,
            error_message=result.error_message,
            started_at=result.started_at,
            finished_at=result.finished_at,
            requested_by=principal.user_id,
        )
        session.add(invocation)
        await session.flush()
        await append_audit(
            session,
            request,
            action="plugin.invoked",
            resource_type="plugin_invocation",
            outcome="success" if result.success else "failure",
            principal=principal,
            project_id=project_id,
            resource_id=str(invocation.id),
            metadata={
                "plugin_id": plugin.plugin_id,
                "version": plugin.version,
                "capability": payload.capability,
                "operation": payload.operation,
                "integration_id": str(connection.id),
                "evidence_count": len(result.evidence),
            },
        )
    return PluginInvocationResponse(
        invocation_id=invocation.id,
        plugin_id=plugin.plugin_id,
        capability=payload.capability,
        operation=payload.operation,
        result=result,
    )


async def _register_manifest(
    session: AsyncSession,
    *,
    principal: Principal,
    manifest: PluginManifest,
    enabled: bool,
) -> tuple[PluginDefinition, bool]:
    if manifest.entrypoint not in ALLOWED_ENTRYPOINTS:
        raise ApplicationError(code="AIOPS_8702", message="插件执行入口不受支持", status_code=422)
    existing = await session.scalar(
        select(PluginDefinition).where(
            PluginDefinition.tenant_id == principal.tenant_id,
            PluginDefinition.plugin_id == manifest.plugin_id,
            PluginDefinition.version == manifest.version,
        )
    )
    if existing is not None:
        return existing, False
    document = manifest.model_dump(mode="json")
    manifest_hash = hashlib.sha256(
        json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    row = PluginDefinition(
        tenant_id=principal.tenant_id,
        plugin_id=manifest.plugin_id,
        name=manifest.name,
        version=manifest.version,
        vendor=manifest.vendor,
        description=manifest.description,
        capabilities=manifest.capabilities,
        supported_asset_types=manifest.supported_asset_types,
        configuration_schema=manifest.configuration_schema,
        credential_types=manifest.credential_types,
        required_permissions=manifest.required_permissions,
        risk_level=manifest.risk_level,
        timeout_seconds=manifest.timeout,
        retry_policy=manifest.retry_policy,
        idempotent=manifest.idempotent,
        health_check=manifest.health_check,
        entrypoint=manifest.entrypoint,
        enabled=enabled,
        manifest_hash=manifest_hash,
        created_by=principal.user_id,
    )
    session.add(row)
    await session.flush()
    return row, True
