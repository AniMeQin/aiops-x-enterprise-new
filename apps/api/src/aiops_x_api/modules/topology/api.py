from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.modules.cmdb.application import topology_snapshot
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.topology.schemas import TopologyResponse

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=TopologyResponse)
async def get_topology(
    principal: Annotated[Principal, Depends(require_permission("topology:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[UUID | None, Query()] = None,
    root_asset_id: Annotated[UUID | None, Query()] = None,
    max_nodes: Annotated[int, Query(ge=1, le=1000)] = 300,
) -> TopologyResponse:
    if project_id is not None:
        ensure_project_scope(principal, project_id)
    snapshot = await topology_snapshot(
        session,
        tenant_id=principal.tenant_id,
        project_id=project_id,
        root_asset_id=root_asset_id,
        max_nodes=max_nodes,
        allowed_project_ids=scoped_project_ids(principal),
        allowed_environments_by_project=(
            {grant.project_id: grant.environment_constraints for grant in principal.project_grants}
            if principal.project_grants is not None
            else None
        ),
        allowed_tags_by_project=(
            {grant.project_id: grant.asset_tag_constraints for grant in principal.project_grants}
            if principal.project_grants is not None
            else None
        ),
        gxp_projects=(
            frozenset(grant.project_id for grant in principal.project_grants if grant.gxp_access)
            if principal.project_grants is not None
            else None
        ),
    )
    return TopologyResponse.model_validate(snapshot)
