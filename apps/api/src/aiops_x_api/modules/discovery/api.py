from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.discovery.adapters import AsyncTcpDiscoveryBackend
from aiops_x_api.modules.discovery.application import (
    collect_observations,
    complete_run,
    confirm_candidate,
    fail_run,
    get_candidate,
    get_job,
    reject_candidate,
    start_run,
)
from aiops_x_api.modules.discovery.infrastructure.models import DiscoveryCandidate, DiscoveryJob
from aiops_x_api.modules.discovery.ports import DiscoveryBackend
from aiops_x_api.modules.discovery.schemas import (
    CandidateConfirm,
    CandidateConfirmationResponse,
    CandidateDecision,
    DiscoveryCandidatePage,
    DiscoveryCandidateResponse,
    DiscoveryJobCreate,
    DiscoveryJobPage,
    DiscoveryJobResponse,
    DiscoveryRunResponse,
)
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/discovery", tags=["discovery"])


def get_discovery_backend() -> DiscoveryBackend:
    return AsyncTcpDiscoveryBackend()


@router.get("/jobs", response_model=DiscoveryJobPage)
async def list_jobs(
    principal: Annotated[Principal, Depends(require_permission("discovery:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> DiscoveryJobPage:
    filters = [DiscoveryJob.tenant_id == principal.tenant_id]
    allowed = scoped_project_ids(principal)
    if allowed is not None:
        filters.append(DiscoveryJob.project_id.in_(allowed))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(DiscoveryJob.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(DiscoveryJob).where(*filters))
    rows = (
        await session.scalars(
            select(DiscoveryJob)
            .where(*filters)
            .order_by(DiscoveryJob.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return DiscoveryJobPage(
        items=[DiscoveryJobResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/jobs", response_model=DiscoveryJobResponse, status_code=201)
async def create_job(
    payload: DiscoveryJobCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("discovery:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DiscoveryJobResponse:
    ensure_project_scope(principal, payload.project_id)
    # Validate the host bound and RFC1918 restriction before persisting the job.
    AsyncTcpDiscoveryBackend._hosts(tuple(payload.networks), payload.max_hosts)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        existing = await session.scalar(
            select(DiscoveryJob.id).where(
                DiscoveryJob.tenant_id == principal.tenant_id,
                DiscoveryJob.project_id == payload.project_id,
                DiscoveryJob.name == payload.name,
            )
        )
        if existing is not None:
            raise ApplicationError(
                code="AIOPS_3312", message="项目内发现任务名称已存在", status_code=409
            )
        job = DiscoveryJob(
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            discovery_type="private_tcp",
            next_run_at=datetime.now(UTC) if payload.schedule_enabled else None,
            **payload.model_dump(),
        )
        session.add(job)
        await session.flush()
        await append_audit(
            session,
            request,
            action="discovery.job.created",
            resource_type="discovery_job",
            outcome="success",
            principal=principal,
            project_id=job.project_id,
            resource_id=str(job.id),
            metadata={"network_count": len(job.networks), "port_count": len(job.ports)},
        )
    return DiscoveryJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/run", response_model=DiscoveryRunResponse, status_code=201)
async def run_job(
    job_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("discovery:run"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    backend: Annotated[DiscoveryBackend, Depends(get_discovery_backend)],
) -> DiscoveryRunResponse:
    async with session.begin():
        job, run = await start_run(
            session,
            tenant_id=principal.tenant_id,
            job_id=job_id,
            requested_by=principal.user_id,
        )
        ensure_project_scope(principal, job.project_id)
        job_scope = (
            job.id,
            job.project_id,
            tuple(job.networks),
            tuple(job.ports),
            job.timeout_seconds,
            job.max_hosts,
        )
    try:
        observations = await collect_observations(
            networks=job_scope[2],
            ports=job_scope[3],
            timeout_seconds=job_scope[4],
            max_hosts=job_scope[5],
            backend=backend,
        )
        async with session.begin():
            job = await get_job(session, tenant_id=principal.tenant_id, job_id=job_scope[0])
            run = await complete_run(session, job=job, run=run, observations=observations)
            await append_audit(
                session,
                request,
                action="discovery.run.completed",
                resource_type="discovery_run",
                outcome="success",
                principal=principal,
                project_id=job_scope[1],
                resource_id=str(run.id),
                metadata={
                    "observed_host_count": run.observed_host_count,
                    "candidate_count": run.candidate_count,
                },
            )
    except ApplicationError as error:
        async with session.begin():
            await fail_run(
                session,
                tenant_id=principal.tenant_id,
                job_id=job_scope[0],
                run_id=run.id,
                error_code=error.code,
            )
            await append_audit(
                session,
                request,
                action="discovery.run.completed",
                resource_type="discovery_run",
                outcome="failure",
                principal=principal,
                project_id=job_scope[1],
                resource_id=str(run.id),
                metadata={"error_code": error.code},
            )
        raise
    except Exception:
        async with session.begin():
            await fail_run(
                session,
                tenant_id=principal.tenant_id,
                job_id=job_scope[0],
                run_id=run.id,
                error_code="AIOPS_3313",
            )
            await append_audit(
                session,
                request,
                action="discovery.run.completed",
                resource_type="discovery_run",
                outcome="failure",
                principal=principal,
                project_id=job_scope[1],
                resource_id=str(run.id),
                metadata={"error_code": "AIOPS_3313"},
            )
        raise ApplicationError(
            code="AIOPS_3313", message="发现后端执行失败", status_code=502
        ) from None
    return DiscoveryRunResponse.model_validate(run)


@router.get("/candidates", response_model=DiscoveryCandidatePage)
async def list_candidates(
    principal: Annotated[Principal, Depends(require_permission("discovery:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(pattern="^(pending|confirmed|rejected|stale)$")] = None,
) -> DiscoveryCandidatePage:
    filters = [DiscoveryCandidate.tenant_id == principal.tenant_id]
    allowed = scoped_project_ids(principal)
    if allowed is not None:
        filters.append(DiscoveryCandidate.project_id.in_(allowed))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(DiscoveryCandidate.project_id == project_id)
    if status is not None:
        filters.append(DiscoveryCandidate.status == status)
    total = await session.scalar(
        select(func.count()).select_from(DiscoveryCandidate).where(*filters)
    )
    rows = (
        await session.scalars(
            select(DiscoveryCandidate)
            .where(*filters)
            .order_by(DiscoveryCandidate.last_seen_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return DiscoveryCandidatePage(
        items=[DiscoveryCandidateResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post(
    "/candidates/{candidate_id}/confirm",
    response_model=CandidateConfirmationResponse,
)
async def confirm(
    candidate_id: UUID,
    payload: CandidateConfirm,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("discovery:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CandidateConfirmationResponse:
    async with session.begin():
        candidate = await get_candidate(
            session, tenant_id=principal.tenant_id, candidate_id=candidate_id
        )
        ensure_project_scope(principal, candidate.project_id)
        if payload.existing_asset_id is None:
            ensure_asset_scope(
                principal,
                project_id=candidate.project_id,
                environment=payload.environment,
                tags=payload.tags,
                gxp_classification=payload.gxp_classification,
            )
        candidate, asset = await confirm_candidate(
            session,
            tenant_id=principal.tenant_id,
            candidate_id=candidate_id,
            reviewed_by=principal.user_id,
            **payload.model_dump(),
        )
        await append_audit(
            session,
            request,
            action="discovery.candidate.confirmed",
            resource_type="discovery_candidate",
            outcome="success",
            principal=principal,
            project_id=candidate.project_id,
            resource_id=str(candidate.id),
            metadata={
                "asset_id": str(asset.id),
                "created_asset": payload.existing_asset_id is None,
            },
        )
    return CandidateConfirmationResponse(
        candidate_id=candidate.id, asset_id=asset.id, status=candidate.status
    )


@router.post("/candidates/{candidate_id}/decision", response_model=DiscoveryCandidateResponse)
async def decide(
    candidate_id: UUID,
    payload: CandidateDecision,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("discovery:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DiscoveryCandidateResponse:
    async with session.begin():
        candidate = await get_candidate(
            session, tenant_id=principal.tenant_id, candidate_id=candidate_id
        )
        ensure_project_scope(principal, candidate.project_id)
        candidate = await reject_candidate(
            session,
            tenant_id=principal.tenant_id,
            candidate_id=candidate_id,
            reviewed_by=principal.user_id,
        )
        await append_audit(
            session,
            request,
            action="discovery.candidate.rejected",
            resource_type="discovery_candidate",
            outcome="success",
            principal=principal,
            project_id=candidate.project_id,
            resource_id=str(candidate.id),
            metadata={"reason": payload.reason},
        )
    return DiscoveryCandidateResponse.model_validate(candidate)
