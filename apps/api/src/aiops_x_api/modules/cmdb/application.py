from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.modules.cmdb.infrastructure.models import Asset, AssetRelation


async def get_asset_for_scope(session: AsyncSession, *, tenant_id: UUID, asset_id: UUID) -> Asset:
    asset = await session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.tenant_id == tenant_id)
    )
    if asset is None:
        from aiops_x_api.core.errors import ApplicationError

        raise ApplicationError(code="AIOPS_3104", message="资产不存在", status_code=404)
    return asset


async def require_asset_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_ids: list[UUID],
) -> list[Asset]:
    if not asset_ids:
        return []
    rows = (
        await session.scalars(
            select(Asset).where(
                Asset.id.in_(asset_ids),
                Asset.tenant_id == tenant_id,
                Asset.project_id == project_id,
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(asset_ids):
        from aiops_x_api.core.errors import ApplicationError

        raise ApplicationError(
            code="AIOPS_3105",
            message="关联资产不存在或超出项目范围",
            status_code=404,
        )
    return [by_id[asset_id] for asset_id in asset_ids]


async def dependency_correlation_key(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    service: str,
) -> str:
    """Return a stable key for the active dependency component containing an asset."""
    project_asset_ids = set(
        (
            await session.scalars(
                select(Asset.id).where(
                    Asset.tenant_id == tenant_id,
                    Asset.project_id == project_id,
                    Asset.lifecycle_status != "retired",
                )
            )
        ).all()
    )
    if asset_id not in project_asset_ids:
        return f"asset:{asset_id}:service:{service}"
    rows = (
        await session.scalars(
            select(AssetRelation).where(
                AssetRelation.tenant_id == tenant_id,
                AssetRelation.source_asset_id.in_(project_asset_ids),
                AssetRelation.target_asset_id.in_(project_asset_ids),
                AssetRelation.relation_type.in_(
                    ["DEPENDS_ON", "RUNS_ON", "CONNECTS_TO", "STORES_DATA_IN", "EXPOSES"]
                ),
                or_(
                    AssetRelation.expires_at.is_(None),
                    AssetRelation.expires_at > datetime.now(UTC),
                ),
            )
        )
    ).all()
    graph: dict[UUID, set[UUID]] = {}
    for relation in rows:
        graph.setdefault(relation.source_asset_id, set()).add(relation.target_asset_id)
        graph.setdefault(relation.target_asset_id, set()).add(relation.source_asset_id)
    component = {asset_id}
    frontier = [asset_id]
    while frontier and len(component) < 200:
        current = frontier.pop()
        for neighbor in graph.get(current, set()):
            if neighbor not in component:
                component.add(neighbor)
                frontier.append(neighbor)
    if len(component) == 1:
        return f"asset:{asset_id}:service:{service}"
    root = min(str(item) for item in component)
    return f"dependency:{root}:service:{service}"


async def topology_snapshot(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID | None,
    root_asset_id: UUID | None,
    max_nodes: int,
    allowed_project_ids: frozenset[UUID] | None = None,
    allowed_environments_by_project: dict[UUID, frozenset[str]] | None = None,
    allowed_tags_by_project: dict[UUID, frozenset[str]] | None = None,
    gxp_projects: frozenset[UUID] | None = None,
) -> dict[str, Any]:
    filters = [Asset.tenant_id == tenant_id, Asset.lifecycle_status != "retired"]
    if allowed_project_ids is not None:
        filters.append(Asset.project_id.in_(allowed_project_ids))
    if project_id is not None:
        filters.append(Asset.project_id == project_id)
    if root_asset_id is not None:
        relation_rows = (
            await session.scalars(
                select(AssetRelation).where(
                    AssetRelation.tenant_id == tenant_id,
                    or_(
                        AssetRelation.source_asset_id == root_asset_id,
                        AssetRelation.target_asset_id == root_asset_id,
                    ),
                    or_(
                        AssetRelation.expires_at.is_(None),
                        AssetRelation.expires_at > datetime.now(UTC),
                    ),
                )
            )
        ).all()
        scoped_ids = {root_asset_id}
        for relation in relation_rows:
            scoped_ids.add(relation.source_asset_id)
            scoped_ids.add(relation.target_asset_id)
        filters.append(Asset.id.in_(scoped_ids))
    assets = (
        await session.scalars(
            select(Asset)
            .where(*filters)
            .order_by(Asset.criticality.desc(), Asset.name)
            .limit(max_nodes)
        )
    ).all()
    if allowed_project_ids is not None:
        assets = [
            asset
            for asset in assets
            if (
                not (allowed_environments_by_project or {}).get(asset.project_id)
                or asset.environment in (allowed_environments_by_project or {})[asset.project_id]
            )
            and (
                not (allowed_tags_by_project or {}).get(asset.project_id)
                or bool(
                    set(asset.tags).intersection((allowed_tags_by_project or {})[asset.project_id])
                )
            )
            and (
                asset.gxp_classification != "gxp"
                or asset.project_id in (gxp_projects or frozenset())
            )
        ]
    asset_ids = {asset.id for asset in assets}
    relations = (
        (
            await session.scalars(
                select(AssetRelation).where(
                    AssetRelation.tenant_id == tenant_id,
                    AssetRelation.source_asset_id.in_(asset_ids),
                    AssetRelation.target_asset_id.in_(asset_ids),
                    or_(
                        AssetRelation.expires_at.is_(None),
                        AssetRelation.expires_at > datetime.now(UTC),
                    ),
                )
            )
        ).all()
        if asset_ids
        else []
    )
    return {
        "generated_at": datetime.now(UTC),
        "nodes": [
            {
                "id": asset.id,
                "asset_id": asset.asset_id,
                "project_id": asset.project_id,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "criticality": asset.criticality,
                "gxp_classification": asset.gxp_classification,
                "lifecycle_status": asset.lifecycle_status,
                "agent_status": asset.agent_status,
                "monitoring_status": asset.monitoring_status,
                "environment": asset.environment,
            }
            for asset in assets
        ],
        "edges": [
            {
                "id": relation.id,
                "source_asset_id": relation.source_asset_id,
                "target_asset_id": relation.target_asset_id,
                "relation_type": relation.relation_type,
                "source": relation.source,
                "confidence": relation.confidence,
                "manually_confirmed": relation.manually_confirmed,
            }
            for relation in relations
        ],
    }
