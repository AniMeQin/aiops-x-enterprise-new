import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.evidence.application import require_evidence_refs
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.integrations.application import get_integration_connection
from aiops_x_api.modules.security_center.infrastructure.models import (
    RemediationRecord,
    RiskRecord,
    SecurityFinding,
    SecurityTicket,
    VulnerabilityRecord,
)
from aiops_x_api.modules.security_center.schemas import (
    FindingCreate,
    FindingDetail,
    FindingPage,
    FindingResponse,
    FindingStatusUpdate,
    RemediationResponse,
    RiskResponse,
    TicketResponse,
    VulnerabilityResponse,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/security", tags=["security-center"])


@router.get("/findings", response_model=FindingPage)
async def list_findings(
    principal: Annotated[Principal, Depends(require_permission("security:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> FindingPage:
    filters = [SecurityFinding.tenant_id == principal.tenant_id]
    if (allowed := scoped_project_ids(principal)) is not None:
        filters.append(SecurityFinding.project_id.in_(allowed))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(SecurityFinding.project_id == project_id)
    if severity:
        filters.append(SecurityFinding.severity == severity)
    if status:
        filters.append(SecurityFinding.status == status)
    total = await session.scalar(select(func.count()).select_from(SecurityFinding).where(*filters))
    rows = (
        await session.scalars(
            select(SecurityFinding)
            .where(*filters)
            .order_by(SecurityFinding.last_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return FindingPage(
        items=[FindingResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/findings", response_model=FindingResponse, status_code=201)
async def ingest_finding(
    payload: FindingCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("security:ingest"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingResponse:
    ensure_project_scope(principal, payload.project_id)
    if payload.last_seen_at < payload.first_seen_at:
        raise ApplicationError(
            code="AIOPS_8801", message="最近发现时间不能早于首次发现", status_code=422
        )
    fingerprint = hashlib.sha256(
        f"{principal.tenant_id}:{payload.source}:{payload.external_id}".encode()
    ).hexdigest()
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        if payload.asset_id is not None:
            asset = await get_asset_for_scope(
                session, tenant_id=principal.tenant_id, asset_id=payload.asset_id
            )
            if asset.project_id != payload.project_id:
                raise ApplicationError(
                    code="AIOPS_8802", message="安全发现与资产项目不一致", status_code=409
                )
            ensure_asset_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        if payload.integration_id is not None:
            connection = await get_integration_connection(
                session,
                tenant_id=principal.tenant_id,
                integration_id=payload.integration_id,
            )
            if connection.project_id not in {None, payload.project_id}:
                raise ApplicationError(
                    code="AIOPS_8803",
                    message="安全发现与集成项目不一致",
                    status_code=409,
                )
        await require_evidence_refs(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            evidence_ids=payload.evidence_ids,
        )
        existing = await session.scalar(
            select(SecurityFinding).where(
                SecurityFinding.tenant_id == principal.tenant_id,
                SecurityFinding.source == payload.source,
                SecurityFinding.external_id == payload.external_id,
            )
        )
        if existing is not None:
            if existing.project_id != payload.project_id:
                raise ApplicationError(
                    code="AIOPS_8805",
                    message="同一外部发现不能跨项目迁移",
                    status_code=409,
                )
            existing.asset_id = payload.asset_id
            existing.integration_id = payload.integration_id
            existing.category = payload.category
            existing.title = payload.title.strip()
            existing.description = payload.description.strip()
            existing.last_seen_at = payload.last_seen_at
            existing.severity = payload.severity
            existing.cve_ids = sorted(set(payload.cve_ids))
            existing.evidence_ids = [str(item) for item in payload.evidence_ids]
            existing.raw_data_ref = payload.raw_data_ref
            existing.metadata_json = payload.metadata
            finding = existing
            await _replace_normalized_records(session, finding, payload)
            action = "security.finding.refreshed"
        else:
            finding = SecurityFinding(
                finding_id=f"FND-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}",
                tenant_id=principal.tenant_id,
                project_id=payload.project_id,
                asset_id=payload.asset_id,
                integration_id=payload.integration_id,
                source=payload.source,
                external_id=payload.external_id,
                fingerprint=fingerprint,
                category=payload.category,
                title=payload.title.strip(),
                description=payload.description.strip(),
                severity=payload.severity,
                status="open",
                cve_ids=sorted(set(payload.cve_ids)),
                evidence_ids=[str(item) for item in payload.evidence_ids],
                raw_data_ref=payload.raw_data_ref,
                metadata_json=payload.metadata,
                first_seen_at=payload.first_seen_at,
                last_seen_at=payload.last_seen_at,
                created_by=principal.user_id,
            )
            session.add(finding)
            await session.flush()
            if payload.vulnerability is not None:
                session.add(
                    VulnerabilityRecord(finding_id=finding.id, **payload.vulnerability.model_dump())
                )
            if payload.remediation is not None:
                session.add(
                    RemediationRecord(finding_id=finding.id, **payload.remediation.model_dump())
                )
            session.add(
                RiskRecord(
                    finding_id=finding.id,
                    likelihood=payload.risk.likelihood,
                    impact=payload.risk.impact,
                    score=payload.risk.likelihood * payload.risk.impact,
                )
            )
            if payload.ticket is not None:
                session.add(SecurityTicket(finding_id=finding.id, **payload.ticket.model_dump()))
            action = "security.finding.created"
        await append_audit(
            session,
            request,
            action=action,
            resource_type="security_finding",
            outcome="success",
            principal=principal,
            project_id=finding.project_id,
            resource_id=str(finding.id),
            metadata={"source": finding.source, "severity": finding.severity},
        )
        await session.flush()
        await session.refresh(finding)
    return FindingResponse.model_validate(finding)


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def get_finding(
    finding_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("security:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingDetail:
    finding = await _finding_in_scope(session, principal, finding_id)
    return await _finding_detail(session, finding)


@router.patch("/findings/{finding_id}/status", response_model=FindingResponse)
async def update_finding_status(
    finding_id: UUID,
    payload: FindingStatusUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("security:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FindingResponse:
    async with session.begin():
        finding = await _finding_in_scope(session, principal, finding_id, for_update=True)
        finding.status = payload.status
        finding.resolved_at = (
            datetime.now(UTC)
            if payload.status in {"resolved", "accepted", "false_positive"}
            else None
        )
        risk = await session.scalar(select(RiskRecord).where(RiskRecord.finding_id == finding.id))
        remediation = await session.scalar(
            select(RemediationRecord).where(RemediationRecord.finding_id == finding.id)
        )
        if risk is not None:
            risk.accepted = payload.status == "accepted"
            risk.accepted_by = principal.user_id if risk.accepted else None
            risk.acceptance_reason = payload.reason if risk.accepted else None
        if remediation is not None:
            remediation.status = {
                "remediating": "in_progress",
                "resolved": "completed",
                "accepted": "risk_accepted",
                "false_positive": "not_applicable",
            }.get(payload.status, remediation.status)
        await append_audit(
            session,
            request,
            action="security.finding.status.updated",
            resource_type="security_finding",
            outcome="success",
            principal=principal,
            project_id=finding.project_id,
            resource_id=str(finding.id),
            metadata={"status": payload.status, "reason": payload.reason},
        )
        await session.flush()
        await session.refresh(finding)
    return FindingResponse.model_validate(finding)


async def _finding_in_scope(
    session: AsyncSession,
    principal: Principal,
    finding_id: UUID,
    *,
    for_update: bool = False,
) -> SecurityFinding:
    statement = select(SecurityFinding).where(
        SecurityFinding.id == finding_id,
        SecurityFinding.tenant_id == principal.tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    finding = await session.scalar(statement)
    if finding is None:
        raise ApplicationError(code="AIOPS_8804", message="安全发现不存在", status_code=404)
    ensure_project_scope(principal, finding.project_id)
    return finding


async def _finding_detail(session: AsyncSession, finding: SecurityFinding) -> FindingDetail:
    vulnerability = await session.scalar(
        select(VulnerabilityRecord).where(VulnerabilityRecord.finding_id == finding.id)
    )
    remediation = await session.scalar(
        select(RemediationRecord).where(RemediationRecord.finding_id == finding.id)
    )
    risk = await session.scalar(select(RiskRecord).where(RiskRecord.finding_id == finding.id))
    ticket = await session.scalar(
        select(SecurityTicket).where(SecurityTicket.finding_id == finding.id)
    )
    if risk is None:
        raise ApplicationError(
            code="AIOPS_8806",
            message="安全发现风险记录缺失",
            status_code=409,
        )
    return FindingDetail(
        **FindingResponse.model_validate(finding).model_dump(),
        vulnerability=(
            VulnerabilityResponse.model_validate(vulnerability)
            if vulnerability is not None
            else None
        ),
        remediation=(
            RemediationResponse.model_validate(remediation) if remediation is not None else None
        ),
        risk=RiskResponse.model_validate(risk),
        ticket=TicketResponse.model_validate(ticket) if ticket is not None else None,
    )


async def _replace_normalized_records(
    session: AsyncSession,
    finding: SecurityFinding,
    payload: FindingCreate,
) -> None:
    vulnerability = await session.scalar(
        select(VulnerabilityRecord).where(VulnerabilityRecord.finding_id == finding.id)
    )
    if payload.vulnerability is not None:
        values = payload.vulnerability.model_dump()
        if vulnerability is None:
            session.add(VulnerabilityRecord(finding_id=finding.id, **values))
        else:
            for field, value in values.items():
                setattr(vulnerability, field, value)
    remediation = await session.scalar(
        select(RemediationRecord).where(RemediationRecord.finding_id == finding.id)
    )
    if payload.remediation is not None:
        values = payload.remediation.model_dump()
        if remediation is None:
            session.add(RemediationRecord(finding_id=finding.id, **values))
        else:
            for field, value in values.items():
                setattr(remediation, field, value)
    risk = await session.scalar(select(RiskRecord).where(RiskRecord.finding_id == finding.id))
    if risk is None:
        session.add(
            RiskRecord(
                finding_id=finding.id,
                likelihood=payload.risk.likelihood,
                impact=payload.risk.impact,
                score=payload.risk.likelihood * payload.risk.impact,
            )
        )
    elif not risk.accepted:
        risk.likelihood = payload.risk.likelihood
        risk.impact = payload.risk.impact
        risk.score = payload.risk.likelihood * payload.risk.impact
    ticket = await session.scalar(
        select(SecurityTicket).where(SecurityTicket.finding_id == finding.id)
    )
    if payload.ticket is not None:
        values = payload.ticket.model_dump()
        if ticket is None:
            session.add(SecurityTicket(finding_id=finding.id, **values))
        else:
            for field, value in values.items():
                setattr(ticket, field, value)
