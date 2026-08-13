from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.modules.audit.application import verify_audit_entry
from aiops_x_api.modules.audit.infrastructure.models import AuditLog
from aiops_x_api.modules.audit.schemas import (
    AuditIntegrityResponse,
    AuditLogPage,
    AuditLogResponse,
)
from aiops_x_api.modules.identity.security import Principal, require_permission, scoped_project_ids

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    principal: Annotated[Principal, Depends(require_permission("audit:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    action: Annotated[str | None, Query(max_length=120)] = None,
    outcome: Annotated[str | None, Query(max_length=32)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
) -> AuditLogPage:
    filters = [AuditLog.tenant_id == principal.tenant_id]
    if (allowed := scoped_project_ids(principal)) is not None:
        filters.append(AuditLog.project_id.in_(allowed))
    if action:
        filters.append(AuditLog.action == action)
    if outcome:
        filters.append(AuditLog.outcome == outcome)
    if created_from:
        filters.append(AuditLog.created_at >= created_from)
    if created_to:
        filters.append(AuditLog.created_at <= created_to)
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
    logs = (
        await session.scalars(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.get("/integrity", response_model=AuditIntegrityResponse)
async def verify_audit_integrity(
    principal: Annotated[Principal, Depends(require_permission("audit:verify"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuditIntegrityResponse:
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == principal.tenant_id)
            .order_by(AuditLog.sequence_no)
        )
    ).all()
    previous_hash = "0" * 64
    for row in rows:
        if not verify_audit_entry(row, previous_hash):
            return AuditIntegrityResponse(
                valid=False,
                checked_entries=len(rows),
                first_sequence=rows[0].sequence_no if rows else None,
                last_sequence=rows[-1].sequence_no if rows else None,
                broken_sequence=row.sequence_no,
                message="审计哈希链校验失败",
            )
        previous_hash = row.entry_hash
    return AuditIntegrityResponse(
        valid=True,
        checked_entries=len(rows),
        first_sequence=rows[0].sequence_no if rows else None,
        last_sequence=rows[-1].sequence_no if rows else None,
        broken_sequence=None,
        message="审计哈希链完整",
    )
