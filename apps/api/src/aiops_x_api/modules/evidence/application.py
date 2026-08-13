from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.evidence.infrastructure.models import EvidenceRecord


def human_evidence_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"EVD-{timestamp}-{uuid4().hex[:8].upper()}"


async def get_evidence_in_scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    evidence_id: UUID,
    project_id: UUID | None = None,
) -> EvidenceRecord:
    filters = [EvidenceRecord.id == evidence_id, EvidenceRecord.tenant_id == tenant_id]
    if project_id is not None:
        filters.append(EvidenceRecord.project_id == project_id)
    evidence = await session.scalar(select(EvidenceRecord).where(*filters))
    if evidence is None:
        raise ApplicationError(code="AIOPS_8004", message="证据不存在", status_code=404)
    return evidence


async def require_evidence_refs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    evidence_ids: list[UUID],
) -> None:
    if not evidence_ids:
        return
    rows = (
        await session.scalars(
            select(EvidenceRecord.id).where(
                EvidenceRecord.id.in_(evidence_ids),
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.project_id == project_id,
            )
        )
    ).all()
    if set(rows) != set(evidence_ids):
        raise ApplicationError(
            code="AIOPS_8005",
            message="证据引用不存在或超出当前项目范围",
            status_code=422,
        )


async def load_evidence_records(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    evidence_ids: list[UUID],
) -> list[EvidenceRecord]:
    await require_evidence_refs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        evidence_ids=evidence_ids,
    )
    rows = (
        await session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.id.in_(evidence_ids),
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.project_id == project_id,
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    return [by_id[evidence_id] for evidence_id in evidence_ids]
