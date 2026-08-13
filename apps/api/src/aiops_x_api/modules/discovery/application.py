import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.cmdb.application import (
    create_discovered_asset,
    find_assets_by_ip,
    get_asset_for_scope,
)
from aiops_x_api.modules.cmdb.contracts import AssetView
from aiops_x_api.modules.discovery.infrastructure.models import (
    DiscoveryCandidate,
    DiscoveryJob,
    DiscoveryRun,
)
from aiops_x_api.modules.discovery.ports import DiscoveryBackend, DiscoveryObservation


async def get_job(session: AsyncSession, *, tenant_id: UUID, job_id: UUID) -> DiscoveryJob:
    job = await session.scalar(
        select(DiscoveryJob).where(DiscoveryJob.id == job_id, DiscoveryJob.tenant_id == tenant_id)
    )
    if job is None:
        raise ApplicationError(code="AIOPS_3304", message="发现任务不存在", status_code=404)
    return job


async def get_candidate(
    session: AsyncSession, *, tenant_id: UUID, candidate_id: UUID
) -> DiscoveryCandidate:
    candidate = await session.scalar(
        select(DiscoveryCandidate).where(
            DiscoveryCandidate.id == candidate_id,
            DiscoveryCandidate.tenant_id == tenant_id,
        )
    )
    if candidate is None:
        raise ApplicationError(code="AIOPS_3305", message="发现候选不存在", status_code=404)
    return candidate


async def start_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
    requested_by: UUID,
) -> tuple[DiscoveryJob, DiscoveryRun]:
    job = await get_job(session, tenant_id=tenant_id, job_id=job_id)
    if not job.enabled:
        raise ApplicationError(code="AIOPS_3306", message="发现任务已停用", status_code=409)
    running = await session.scalar(
        select(DiscoveryRun.id).where(
            DiscoveryRun.discovery_job_id == job.id, DiscoveryRun.status == "running"
        )
    )
    if running is not None:
        raise ApplicationError(code="AIOPS_3307", message="发现任务正在运行", status_code=409)
    now = datetime.now(UTC)
    run = DiscoveryRun(
        tenant_id=job.tenant_id,
        project_id=job.project_id,
        discovery_job_id=job.id,
        requested_by=requested_by,
        status="running",
        started_at=now,
    )
    session.add(run)
    job.run_count += 1
    job.last_run_status = "running"
    job.last_started_at = now
    job.last_error_code = None
    await session.flush()
    return job, run


async def collect_observations(
    *,
    networks: tuple[str, ...],
    ports: tuple[int, ...],
    timeout_seconds: float,
    max_hosts: int,
    backend: DiscoveryBackend,
) -> list[DiscoveryObservation]:
    """Perform network I/O outside a database transaction."""
    return await backend.discover(
        networks=networks,
        ports=ports,
        timeout_seconds=timeout_seconds,
        max_hosts=max_hosts,
    )


async def complete_run(
    session: AsyncSession,
    *,
    job: DiscoveryJob,
    run: DiscoveryRun,
    observations: list[DiscoveryObservation],
) -> DiscoveryRun:
    now = datetime.now(UTC)
    candidate_count = 0
    seen_fingerprints: set[str] = set()
    for observation in observations:
        fingerprint = _fingerprint(job.tenant_id, job.project_id, observation.ip_address)
        seen_fingerprints.add(fingerprint)
        candidate = await session.scalar(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.tenant_id == job.tenant_id,
                DiscoveryCandidate.project_id == job.project_id,
                DiscoveryCandidate.fingerprint == fingerprint,
            )
        )
        matches = await find_assets_by_ip(
            session,
            tenant_id=job.tenant_id,
            project_id=job.project_id,
            ip_address=observation.ip_address,
        )
        match_status = "unique" if len(matches) == 1 else "ambiguous" if matches else "none"
        evidence = {
            "schema_version": "discovery.observation.v1",
            "method": "tcp_connect",
            "observed_at": now.isoformat(),
            "open_ports": list(observation.open_ports),
            "run_id": str(run.id),
            "job_id": str(job.id),
        }
        if candidate is None:
            candidate = DiscoveryCandidate(
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                discovery_job_id=job.id,
                last_run_id=run.id,
                fingerprint=fingerprint,
                ip_address=observation.ip_address,
                observed_ports=list(observation.open_ports),
                evidence=evidence,
                status="pending",
                match_status=match_status,
                matched_asset_id=matches[0].id if len(matches) == 1 else None,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(candidate)
        else:
            candidate.discovery_job_id = job.id
            candidate.last_run_id = run.id
            candidate.observed_ports = list(observation.open_ports)
            candidate.evidence = evidence
            candidate.last_seen_at = now
            candidate.match_status = match_status
            candidate.matched_asset_id = matches[0].id if len(matches) == 1 else None
            if candidate.status in {"rejected", "stale"}:
                candidate.status = "pending"
                candidate.reviewed_by = None
                candidate.reviewed_at = None
        candidate_count += 1
    previous_pending = (
        await session.scalars(
            select(DiscoveryCandidate).where(
                DiscoveryCandidate.tenant_id == job.tenant_id,
                DiscoveryCandidate.project_id == job.project_id,
                DiscoveryCandidate.discovery_job_id == job.id,
                DiscoveryCandidate.status == "pending",
            )
        )
    ).all()
    for candidate in previous_pending:
        if candidate.fingerprint not in seen_fingerprints:
            candidate.status = "stale"
    run.status = "succeeded"
    run.observed_host_count = len(observations)
    run.candidate_count = candidate_count
    run.completed_at = now
    job.last_run_status = "succeeded"
    job.last_completed_at = now
    job.last_error_code = None
    await session.flush()
    return run


async def fail_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    job_id: UUID,
    run_id: UUID,
    error_code: str,
) -> None:
    job = await get_job(session, tenant_id=tenant_id, job_id=job_id)
    run = await session.scalar(
        select(DiscoveryRun).where(DiscoveryRun.id == run_id, DiscoveryRun.tenant_id == tenant_id)
    )
    if run is None:
        return
    now = datetime.now(UTC)
    run.status = "failed"
    run.error_code = error_code
    run.completed_at = now
    job.last_run_status = "failed"
    job.last_completed_at = now
    job.last_error_code = error_code


async def confirm_candidate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    candidate_id: UUID,
    reviewed_by: UUID,
    existing_asset_id: UUID | None,
    asset_id: str | None,
    asset_type: str | None,
    name: str | None,
    environment: str,
    criticality: str,
    gxp_classification: str,
    tags: list[str],
) -> tuple[DiscoveryCandidate, AssetView]:
    candidate = await get_candidate(session, tenant_id=tenant_id, candidate_id=candidate_id)
    if candidate.status == "confirmed":
        raise ApplicationError(code="AIOPS_3308", message="发现候选已确认", status_code=409)
    if existing_asset_id is not None:
        asset = await get_asset_for_scope(session, tenant_id=tenant_id, asset_id=existing_asset_id)
        if (
            asset.project_id != candidate.project_id
            or candidate.ip_address not in asset.ip_addresses
        ):
            raise ApplicationError(
                code="AIOPS_3309",
                message="现有资产必须属于同一项目且包含候选 IP",
                status_code=409,
            )
    else:
        if asset_id is None or asset_type is None or name is None:
            raise ApplicationError(code="AIOPS_3310", message="资产确认字段不完整", status_code=422)
        asset = await create_discovered_asset(
            session,
            tenant_id=tenant_id,
            project_id=candidate.project_id,
            asset_id=asset_id,
            asset_type=asset_type,
            name=name,
            hostname=candidate.hostname,
            ip_addresses=[candidate.ip_address],
            environment=environment,
            criticality=criticality,
            gxp_classification=gxp_classification,
            tags=tags,
            discovery_metadata={
                "candidate_id": str(candidate.id),
                "job_id": str(candidate.discovery_job_id),
                "last_run_id": str(candidate.last_run_id),
                "confirmed_at": datetime.now(UTC).isoformat(),
            },
        )
    candidate.status = "confirmed"
    candidate.match_status = "unique"
    candidate.matched_asset_id = asset.id
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = datetime.now(UTC)
    await session.flush()
    return candidate, asset


async def reject_candidate(
    session: AsyncSession, *, tenant_id: UUID, candidate_id: UUID, reviewed_by: UUID
) -> DiscoveryCandidate:
    candidate = await get_candidate(session, tenant_id=tenant_id, candidate_id=candidate_id)
    if candidate.status == "confirmed":
        raise ApplicationError(code="AIOPS_3311", message="已确认候选不能直接驳回", status_code=409)
    candidate.status = "rejected"
    candidate.reviewed_by = reviewed_by
    candidate.reviewed_at = datetime.now(UTC)
    return candidate


def _fingerprint(tenant_id: UUID, project_id: UUID, ip_address: str) -> str:
    value = f"{tenant_id}:{project_id}:tcp:{ip_address}".encode()
    return hashlib.sha256(value).hexdigest()
