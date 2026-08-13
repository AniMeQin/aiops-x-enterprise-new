from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.evidence.application import get_evidence_in_scope, human_evidence_id
from aiops_x_api.modules.evidence.infrastructure.models import EvidenceRecord
from aiops_x_api.modules.evidence.schemas import EvidenceCreate, EvidencePage, EvidenceResponse
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("", response_model=EvidencePage)
async def list_evidence(
    principal: Annotated[Principal, Depends(require_permission("evidence:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    asset_id: Annotated[UUID | None, Query()] = None,
    evidence_type: Annotated[str | None, Query(max_length=48)] = None,
) -> EvidencePage:
    filters = [EvidenceRecord.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(EvidenceRecord.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(EvidenceRecord.project_id == project_id)
    if asset_id is not None:
        filters.append(EvidenceRecord.asset_id == asset_id)
    if evidence_type:
        filters.append(EvidenceRecord.evidence_type == evidence_type)
    total = await session.scalar(select(func.count()).select_from(EvidenceRecord).where(*filters))
    rows = (
        await session.scalars(
            select(EvidenceRecord)
            .where(*filters)
            .order_by(EvidenceRecord.observed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return EvidencePage(
        items=[EvidenceResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("", response_model=EvidenceResponse, status_code=201)
async def create_evidence(
    payload: EvidenceCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("evidence:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvidenceResponse:
    ensure_project_scope(principal, payload.project_id)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        record = EvidenceRecord(
            evidence_id=human_evidence_id(),
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            asset_id=payload.asset_id,
            evidence_type=payload.evidence_type,
            title=payload.title.strip(),
            summary=payload.summary.strip(),
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            object_ref=payload.object_ref,
            content_hash=payload.content_hash.lower(),
            classification=payload.classification,
            gxp_classification=payload.gxp_classification,
            observed_at=payload.observed_at,
            metadata_json=payload.metadata,
            created_by=principal.user_id,
        )
        session.add(record)
        await session.flush()
        await append_audit(
            session,
            request,
            action="evidence.created",
            resource_type="evidence",
            outcome="success",
            principal=principal,
            project_id=record.project_id,
            resource_id=str(record.id),
            metadata={"evidence_type": record.evidence_type, "content_hash": record.content_hash},
        )
    return EvidenceResponse.model_validate(record)


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("evidence:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvidenceResponse:
    row = await get_evidence_in_scope(
        session, tenant_id=principal.tenant_id, evidence_id=evidence_id
    )
    ensure_project_scope(principal, row.project_id)
    return EvidenceResponse.model_validate(row)
