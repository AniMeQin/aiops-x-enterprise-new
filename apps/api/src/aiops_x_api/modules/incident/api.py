from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.evidence.application import require_evidence_refs
from aiops_x_api.modules.identity.application import require_active_user_refs
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_asset_scope,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.incident.application import (
    get_incident_in_scope,
    human_incident_number,
    validate_incident_links,
    validate_transition,
)
from aiops_x_api.modules.incident.infrastructure.models import (
    Incident,
    IncidentPostmortem,
    IncidentTimelineEntry,
)
from aiops_x_api.modules.incident.schemas import (
    IncidentCreate,
    IncidentDetail,
    IncidentPage,
    IncidentResponse,
    IncidentUpdate,
    PostmortemResponse,
    PostmortemUpsert,
    TimelineEntryCreate,
    TimelineEntryResponse,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=IncidentPage)
async def list_incidents(
    principal: Annotated[Principal, Depends(require_permission("incident:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
) -> IncidentPage:
    filters = [Incident.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(Incident.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(Incident.project_id == project_id)
    if status:
        filters.append(Incident.status == status)
    if severity:
        filters.append(Incident.severity == severity)
    total = await session.scalar(select(func.count()).select_from(Incident).where(*filters))
    rows = (
        await session.scalars(
            select(Incident)
            .where(*filters)
            .order_by(Incident.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return IncidentPage(
        items=[IncidentResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("", response_model=IncidentResponse, status_code=201)
async def create_incident(
    payload: IncidentCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("incident:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentResponse:
    ensure_project_scope(principal, payload.project_id)
    async with session.begin():
        await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        await require_evidence_refs(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            evidence_ids=payload.evidence_ids,
        )
        linked_assets = await validate_incident_links(
            session,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            source_event_id=payload.source_event_id,
            asset_ids=payload.asset_ids,
            alert_ids=payload.alert_ids,
            change_ids=payload.change_ids,
        )
        for asset in linked_assets:
            ensure_asset_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        await require_active_user_refs(
            session,
            tenant_id=principal.tenant_id,
            user_ids=[
                *payload.participant_ids,
                *([payload.owner_id] if payload.owner_id is not None else []),
            ],
        )
        incident = Incident(
            incident_number=human_incident_number(),
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            source_event_id=payload.source_event_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            severity=payload.severity,
            status="open",
            owner_id=payload.owner_id,
            participant_ids=_uuid_strings(payload.participant_ids),
            impact_scope=payload.impact_scope,
            asset_ids=_uuid_strings(payload.asset_ids),
            alert_ids=_uuid_strings(payload.alert_ids),
            change_ids=_uuid_strings(payload.change_ids),
            evidence_ids=_uuid_strings(payload.evidence_ids),
            sla_policy=payload.sla_policy,
            response_due_at=payload.response_due_at,
            resolution_due_at=payload.resolution_due_at,
            created_by=principal.user_id,
        )
        session.add(incident)
        await session.flush()
        session.add(
            IncidentTimelineEntry(
                tenant_id=incident.tenant_id,
                project_id=incident.project_id,
                incident_id=incident.id,
                occurred_at=datetime.now(UTC),
                entry_type="status_change",
                title="故障记录已创建",
                description=incident.description,
                evidence_ids=incident.evidence_ids,
                metadata_json={"status": "open", "severity": incident.severity},
                created_by=principal.user_id,
            )
        )
        await append_audit(
            session,
            request,
            action="incident.created",
            resource_type="incident",
            outcome="success",
            principal=principal,
            project_id=incident.project_id,
            resource_id=str(incident.id),
            metadata={"incident_number": incident.incident_number, "severity": incident.severity},
        )
    return IncidentResponse.model_validate(incident)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("incident:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentDetail:
    incident = await get_incident_in_scope(
        session, tenant_id=principal.tenant_id, incident_id=incident_id
    )
    ensure_project_scope(principal, incident.project_id)
    timeline = (
        await session.scalars(
            select(IncidentTimelineEntry)
            .where(IncidentTimelineEntry.incident_id == incident.id)
            .order_by(IncidentTimelineEntry.occurred_at, IncidentTimelineEntry.created_at)
        )
    ).all()
    postmortem = await session.scalar(
        select(IncidentPostmortem).where(IncidentPostmortem.incident_id == incident.id)
    )
    return IncidentDetail(
        **IncidentResponse.model_validate(incident).model_dump(),
        timeline=[TimelineEntryResponse.model_validate(row) for row in timeline],
        postmortem=(
            PostmortemResponse.model_validate(postmortem) if postmortem is not None else None
        ),
    )


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: UUID,
    payload: IncidentUpdate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("incident:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentResponse:
    now = datetime.now(UTC)
    async with session.begin():
        incident = await get_incident_in_scope(
            session, tenant_id=principal.tenant_id, incident_id=incident_id, for_update=True
        )
        ensure_project_scope(principal, incident.project_id)
        changes = payload.model_dump(exclude_unset=True)
        if payload.evidence_ids is not None:
            await require_evidence_refs(
                session,
                tenant_id=principal.tenant_id,
                project_id=incident.project_id,
                evidence_ids=payload.evidence_ids,
            )
        linked_assets = await validate_incident_links(
            session,
            tenant_id=principal.tenant_id,
            project_id=incident.project_id,
            source_event_id=incident.source_event_id,
            asset_ids=(
                payload.asset_ids
                if payload.asset_ids is not None
                else _uuid_values(incident.asset_ids)
            ),
            alert_ids=(
                payload.alert_ids
                if payload.alert_ids is not None
                else _uuid_values(incident.alert_ids)
            ),
            change_ids=(
                payload.change_ids
                if payload.change_ids is not None
                else _uuid_values(incident.change_ids)
            ),
        )
        for asset in linked_assets:
            ensure_asset_scope(
                principal,
                project_id=asset.project_id,
                environment=asset.environment,
                tags=asset.tags,
                gxp_classification=asset.gxp_classification,
            )
        effective_owner = payload.owner_id if "owner_id" in changes else incident.owner_id
        effective_participants = (
            payload.participant_ids
            if payload.participant_ids is not None
            else _uuid_values(incident.participant_ids)
        )
        await require_active_user_refs(
            session,
            tenant_id=principal.tenant_id,
            user_ids=[
                *effective_participants,
                *([effective_owner] if effective_owner is not None else []),
            ],
        )
        old_status = incident.status
        if payload.status is not None:
            validate_transition(old_status, payload.status)
        list_fields = {"participant_ids", "asset_ids", "alert_ids", "change_ids", "evidence_ids"}
        for field, value in changes.items():
            if field in list_fields and value is not None:
                value = _uuid_strings(value)
            setattr(incident, field, value)
        if payload.status is not None and payload.status != old_status:
            if payload.status == "acknowledged" and incident.acknowledged_at is None:
                incident.acknowledged_at = now
            if payload.status == "resolved":
                incident.resolved_at = now
            if payload.status == "closed":
                postmortem = await session.scalar(
                    select(IncidentPostmortem).where(
                        IncidentPostmortem.incident_id == incident.id,
                        IncidentPostmortem.status.in_(["approved", "published"]),
                    )
                )
                if postmortem is None:
                    raise ApplicationError(
                        code="AIOPS_8110",
                        message="故障关闭前必须完成并批准复盘报告",
                        status_code=409,
                    )
                incident.closed_at = now
            session.add(
                IncidentTimelineEntry(
                    tenant_id=incident.tenant_id,
                    project_id=incident.project_id,
                    incident_id=incident.id,
                    occurred_at=now,
                    entry_type="status_change",
                    title=f"状态变更为 {payload.status}",
                    description="",
                    metadata_json={"from": old_status, "to": payload.status},
                    created_by=principal.user_id,
                )
            )
        await append_audit(
            session,
            request,
            action="incident.updated",
            resource_type="incident",
            outcome="success",
            principal=principal,
            project_id=incident.project_id,
            resource_id=str(incident.id),
            metadata={"changed_fields": sorted(changes), "old_status": old_status},
        )
        await session.flush()
        await session.refresh(incident)
    return IncidentResponse.model_validate(incident)


@router.post("/{incident_id}/timeline", response_model=TimelineEntryResponse, status_code=201)
async def add_timeline_entry(
    incident_id: UUID,
    payload: TimelineEntryCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("incident:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TimelineEntryResponse:
    async with session.begin():
        incident = await get_incident_in_scope(
            session, tenant_id=principal.tenant_id, incident_id=incident_id
        )
        ensure_project_scope(principal, incident.project_id)
        await require_evidence_refs(
            session,
            tenant_id=principal.tenant_id,
            project_id=incident.project_id,
            evidence_ids=payload.evidence_ids,
        )
        entry = IncidentTimelineEntry(
            tenant_id=incident.tenant_id,
            project_id=incident.project_id,
            incident_id=incident.id,
            occurred_at=payload.occurred_at,
            entry_type=payload.entry_type,
            title=payload.title.strip(),
            description=payload.description.strip(),
            evidence_ids=_uuid_strings(payload.evidence_ids),
            metadata_json=payload.metadata,
            created_by=principal.user_id,
        )
        session.add(entry)
        await session.flush()
        await append_audit(
            session,
            request,
            action="incident.timeline.added",
            resource_type="incident",
            outcome="success",
            principal=principal,
            project_id=incident.project_id,
            resource_id=str(incident.id),
            metadata={"entry_id": str(entry.id), "entry_type": entry.entry_type},
        )
    return TimelineEntryResponse.model_validate(entry)


@router.put("/{incident_id}/postmortem", response_model=PostmortemResponse)
async def upsert_postmortem(
    incident_id: UUID,
    payload: PostmortemUpsert,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("postmortem:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PostmortemResponse:
    now = datetime.now(UTC)
    async with session.begin():
        incident = await get_incident_in_scope(
            session, tenant_id=principal.tenant_id, incident_id=incident_id
        )
        ensure_project_scope(principal, incident.project_id)
        await require_evidence_refs(
            session,
            tenant_id=principal.tenant_id,
            project_id=incident.project_id,
            evidence_ids=payload.evidence_ids,
        )
        postmortem = await session.scalar(
            select(IncidentPostmortem)
            .where(IncidentPostmortem.incident_id == incident.id)
            .with_for_update()
        )
        values = payload.model_dump(exclude={"evidence_ids"})
        values["evidence_ids"] = _uuid_strings(payload.evidence_ids)
        if postmortem is None:
            postmortem = IncidentPostmortem(
                tenant_id=incident.tenant_id,
                project_id=incident.project_id,
                incident_id=incident.id,
                created_by=principal.user_id,
                **values,
            )
            session.add(postmortem)
        else:
            for field, value in values.items():
                setattr(postmortem, field, value)
        if payload.status in {"approved", "published"}:
            if not {"*", "postmortem:approve"}.intersection(principal.permissions):
                raise ApplicationError(
                    code="AIOPS_8112",
                    message="缺少复盘批准权限",
                    status_code=403,
                )
            if postmortem.created_by == principal.user_id and not {
                "*",
                "postmortem:self-approve",
            }.intersection(principal.permissions):
                raise ApplicationError(
                    code="AIOPS_8113",
                    message="复盘编写人不能批准自己的复盘",
                    status_code=403,
                )
            postmortem.approved_by = principal.user_id
            postmortem.approved_at = now
        else:
            postmortem.approved_by = None
            postmortem.approved_at = None
        await session.flush()
        await append_audit(
            session,
            request,
            action="incident.postmortem.updated",
            resource_type="postmortem",
            outcome="success",
            principal=principal,
            project_id=incident.project_id,
            resource_id=str(postmortem.id),
            metadata={
                "incident_id": str(incident.id),
                "status": postmortem.status,
                "generated_by": postmortem.generated_by,
                "evidence_count": len(postmortem.evidence_ids),
            },
        )
        await session.flush()
        await session.refresh(postmortem)
    return PostmortemResponse.model_validate(postmortem)


def _uuid_strings(values: list[UUID] | list[Any]) -> list[str]:
    return [str(value) for value in values]


def _uuid_values(values: list[str]) -> list[UUID]:
    return [UUID(value) for value in values]
