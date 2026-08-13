import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.ai_gateway.schemas import (
    AIAnalysis,
    AIAssistantAnswer,
    AIAssistantQuery,
    AIStatus,
)
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.automation.infrastructure.models import Runbook
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.evidence.application import load_evidence_records
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
)
from aiops_x_api.modules.operations.infrastructure.models import (
    Alert,
    EventAlert,
    EventTimelineEntry,
    OperationsEvent,
)

router = APIRouter(prefix="/ai", tags=["ai-gateway"])


@router.get("/status", response_model=AIStatus)
async def ai_status(
    _: Annotated[Principal, Depends(require_permission("ai:read"))],
) -> AIStatus:
    return await _engine_status()


@router.post("/events/{event_id}/summary", response_model=AIAnalysis)
async def summarize_event(
    event_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("ai:analyze"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AIAnalysis:
    status = await _engine_status()
    async with session.begin():
        event = await session.scalar(
            select(OperationsEvent)
            .where(
                OperationsEvent.id == event_id,
                OperationsEvent.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if event is None:
            raise ApplicationError(code="AIOPS_5104", message="事件不存在", status_code=404)
        ensure_project_scope(principal, event.project_id)
        if not status.configured:
            event.ai_summary_status = "not_configured"
            event.ai_summary = None
            result = _not_configured_analysis()
            await append_audit(
                session,
                request,
                action="ai.analysis.skipped",
                resource_type="event",
                outcome="unavailable",
                principal=principal,
                project_id=event.project_id,
                resource_id=str(event.id),
                metadata={"reason": "not_configured"},
            )
            return result
        evidence = await _event_evidence(session, event)
        event.ai_summary_status = "processing"

    try:
        result = await _engine_analyze(evidence)
    except ApplicationError:
        async with session.begin():
            event = await session.scalar(
                select(OperationsEvent).where(OperationsEvent.id == event_id).with_for_update()
            )
            if event is not None:
                event.ai_summary_status = "failed"
                await append_audit(
                    session,
                    request,
                    action="ai.analysis.failed",
                    resource_type="event",
                    outcome="failure",
                    principal=principal,
                    project_id=event.project_id,
                    resource_id=str(event.id),
                    metadata={"provider": status.provider},
                )
        raise

    await _validate_event_analysis(session, event.tenant_id, evidence, result)

    async with session.begin():
        event = await session.scalar(
            select(OperationsEvent).where(OperationsEvent.id == event_id).with_for_update()
        )
        if event is None:
            raise ApplicationError(code="AIOPS_5104", message="事件不存在", status_code=404)
        event.ai_summary_status = "completed"
        event.ai_summary = result.summary
        session.add(
            EventTimelineEntry(
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                event_id=event.id,
                occurred_at=datetime.now(UTC),
                category="ai",
                title="AI 事件摘要已生成",
                description=result.summary,
                source_type="ai_analysis",
                source_id=None,
                evidence_refs=[item.model_dump() for item in result.evidence],
                metadata_json={
                    "provider": result.provider,
                    "confidence": result.confidence,
                    "recommendations_are_advisory": True,
                },
            )
        )
        await append_audit(
            session,
            request,
            action="ai.analysis.completed",
            resource_type="event",
            outcome="success",
            principal=principal,
            project_id=event.project_id,
            resource_id=str(event.id),
            metadata={
                "provider": result.provider,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence),
            },
        )
    return result


@router.post("/assistant/query", response_model=AIAssistantAnswer)
async def query_assistant(
    payload: AIAssistantQuery,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("ai:analyze"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AIAssistantAnswer:
    ensure_project_scope(principal, payload.project_id)
    status = await _engine_status()
    if not status.configured:
        async with session.begin():
            await append_audit(
                session,
                request,
                action="ai.assistant.skipped",
                resource_type="ai_assistant",
                outcome="unavailable",
                principal=principal,
                project_id=payload.project_id,
                metadata={"reason": "not_configured"},
            )
        return AIAssistantAnswer(
            status="not_configured",
            answer="AI 服务未配置",
            citations=[],
            confidence=0,
            missing_data=["AI provider configuration"],
            suggested_queries=[],
            risk_notes=["AI 未配置，平台未生成推测性回答。"],
        )
    evidence = await load_evidence_records(
        session,
        tenant_id=principal.tenant_id,
        project_id=payload.project_id,
        evidence_ids=payload.evidence_ids,
    )
    evidence_payload = [
        {
            "evidence_id": record.evidence_id,
            "evidence_type": record.evidence_type,
            "title": record.title,
            "summary": record.summary,
            "source_type": record.source_type,
            "source_ref": record.source_ref,
            "content_hash": record.content_hash,
            "observed_at": record.observed_at.isoformat(),
            "metadata": record.metadata_json,
        }
        for record in evidence
    ]
    result_payload = await _json_request(
        "POST",
        "/api/v1/ai/assistant",
        {"question": payload.question, "evidence": evidence_payload},
    )
    try:
        result = AIAssistantAnswer.model_validate(result_payload)
    except ValueError as exc:
        raise ApplicationError(
            code="AIOPS_7002", message="AI 服务返回的结构无效", status_code=502
        ) from exc
    allowed_citations = {record.evidence_id for record in evidence}
    if not set(result.citations).issubset(allowed_citations):
        raise ApplicationError(
            code="AIOPS_7003", message="AI 返回了未提供的证据引用", status_code=502
        )
    await session.rollback()
    async with session.begin():
        await append_audit(
            session,
            request,
            action="ai.assistant.completed",
            resource_type="ai_assistant",
            outcome="success",
            principal=principal,
            project_id=payload.project_id,
            metadata={
                "provider": result.provider,
                "confidence": result.confidence,
                "evidence_count": len(evidence),
                "citation_count": len(result.citations),
                "question_length": len(payload.question),
            },
        )
    return result


async def _event_evidence(session: AsyncSession, event: OperationsEvent) -> dict[str, Any]:
    asset = await session.scalar(select(Asset).where(Asset.id == event.primary_asset_id))
    alerts = (
        await session.scalars(
            select(Alert)
            .join(EventAlert, EventAlert.alert_id == Alert.id)
            .where(EventAlert.event_id == event.id)
            .order_by(Alert.starts_at.asc())
        )
    ).all()
    timeline = (
        await session.scalars(
            select(EventTimelineEntry)
            .where(EventTimelineEntry.event_id == event.id)
            .order_by(EventTimelineEntry.occurred_at.asc())
        )
    ).all()
    available_evidence_refs = {
        event.event_id,
        *(alert.alert_id for alert in alerts),
        *(
            str(reference.get("ref"))
            for alert in alerts
            for reference in alert.evidence_refs
            if reference.get("ref")
        ),
        *(
            str(reference.get("ref"))
            for entry in timeline
            for reference in entry.evidence_refs
            if reference.get("ref")
        ),
    }
    return {
        "event": {
            "event_id": event.event_id,
            "title": event.title,
            "description": event.description,
            "severity": event.severity,
            "status": event.status,
            "first_seen_at": event.first_seen_at.isoformat(),
            "last_seen_at": event.last_seen_at.isoformat(),
        },
        "asset": (
            {
                "asset_id": asset.asset_id,
                "asset_type": asset.asset_type,
                "name": asset.name,
                "monitoring_status": asset.monitoring_status,
            }
            if asset is not None
            else None
        ),
        "alerts": [
            {
                "alert_id": alert.alert_id,
                "title": alert.title,
                "description": alert.description,
                "severity": alert.severity,
                "status": alert.status,
                "labels": alert.labels,
                "evidence_refs": alert.evidence_refs,
                "duplicate_count": alert.duplicate_count,
            }
            for alert in alerts
        ],
        "timeline": [
            {
                "occurred_at": entry.occurred_at.isoformat(),
                "category": entry.category,
                "title": entry.title,
                "description": entry.description,
                "evidence_refs": entry.evidence_refs,
            }
            for entry in timeline
        ],
        "available_evidence_refs": sorted(available_evidence_refs),
    }


async def _validate_event_analysis(
    session: AsyncSession,
    tenant_id: UUID,
    evidence: dict[str, Any],
    result: AIAnalysis,
) -> None:
    allowed_refs = set(evidence.get("available_evidence_refs", []))
    cited_refs = {item.evidence_ref for item in result.evidence}
    for hypothesis in result.hypotheses:
        cited_refs.update(hypothesis.supporting_evidence_refs)
        cited_refs.update(hypothesis.contradicting_evidence_refs)
    if not cited_refs.issubset(allowed_refs):
        raise ApplicationError(
            code="AIOPS_7003",
            message="AI 返回了未提供的证据引用",
            status_code=502,
        )
    if result.recommended_runbooks:
        registered = set(
            (
                await session.scalars(
                    select(Runbook.name).where(
                        Runbook.tenant_id == tenant_id,
                        Runbook.name.in_(result.recommended_runbooks),
                    )
                )
            ).all()
        )
        if registered != set(result.recommended_runbooks):
            raise ApplicationError(
                code="AIOPS_7004",
                message="AI 返回了未注册的 Runbook 推荐",
                status_code=502,
            )


async def _engine_status() -> AIStatus:
    try:
        payload = await _json_request("GET", "/api/v1/ai/status")
        return AIStatus.model_validate(payload)
    except ApplicationError:
        return AIStatus(
            status="unavailable",
            configured=False,
            provider=None,
            message="AI 服务未配置",
        )


async def _engine_analyze(evidence: dict[str, Any]) -> AIAnalysis:
    payload = await _json_request("POST", "/api/v1/ai/analyze", {"evidence": evidence})
    try:
        return AIAnalysis.model_validate(payload)
    except ValueError as exc:
        raise ApplicationError(
            code="AIOPS_7002",
            message="AI 服务返回的结构无效",
            status_code=502,
        ) from exc


async def _json_request(
    method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    base_url = get_settings().ai_engine_url.rstrip("/")

    def fetch() -> dict[str, Any]:
        encoded = json.dumps(body).encode() if body is not None else None
        request = UrlRequest(  # noqa: S310 -- configured internal service URL
            base_url + path,
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:  # noqa: S310 -- internal service URL
            document = json.loads(response.read(1_048_576))
            if not isinstance(document, dict):
                raise ValueError("AI engine response is not an object")
            return {str(key): value for key, value in document.items()}

    try:
        return await asyncio.to_thread(fetch)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code="AIOPS_7001",
            message="AI 服务暂时不可用",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc


def _not_configured_analysis() -> AIAnalysis:
    return AIAnalysis(
        status="not_configured",
        summary="AI 服务未配置",
        impact="",
        hypotheses=[],
        evidence=[],
        confidence=0,
        missing_data=["AI provider configuration"],
        recommended_actions=[],
        recommended_runbooks=[],
        risk_notes=["AI 未配置，平台未生成任何推测性结论。"],
        rollback_considerations=[],
    )
