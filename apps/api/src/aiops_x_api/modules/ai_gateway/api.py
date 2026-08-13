import asyncio
import json
from typing import Annotated, Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID

from fastapi import APIRouter, Depends, Request
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
from aiops_x_api.modules.automation.contracts import require_registered_runbook_names
from aiops_x_api.modules.evidence.application import load_evidence_records
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
)
from aiops_x_api.modules.operations.application import (
    complete_event_ai_analysis,
    load_ai_event_context,
    update_event_ai_state,
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
        context = await load_ai_event_context(
            session, tenant_id=principal.tenant_id, event_id=event_id
        )
        ensure_project_scope(principal, context.project_id)
        if not status.configured:
            await update_event_ai_state(
                session,
                tenant_id=principal.tenant_id,
                event_id=event_id,
                status="not_configured",
            )
            result = _not_configured_analysis()
            await append_audit(
                session,
                request,
                action="ai.analysis.skipped",
                resource_type="event",
                outcome="unavailable",
                principal=principal,
                project_id=context.project_id,
                resource_id=str(context.id),
                metadata={"reason": "not_configured"},
            )
            return result
        evidence = context.evidence
        await update_event_ai_state(
            session,
            tenant_id=principal.tenant_id,
            event_id=event_id,
            status="processing",
        )

    try:
        result = await _engine_analyze(evidence)
    except ApplicationError:
        async with session.begin():
            failed_context = await update_event_ai_state(
                session,
                tenant_id=principal.tenant_id,
                event_id=event_id,
                status="failed",
            )
            await append_audit(
                session,
                request,
                action="ai.analysis.failed",
                resource_type="event",
                outcome="failure",
                principal=principal,
                project_id=failed_context.project_id,
                resource_id=str(failed_context.id),
                metadata={"provider": status.provider},
            )
        raise

    await _validate_event_analysis(session, context.tenant_id, evidence, result)

    async with session.begin():
        completed_context = await complete_event_ai_analysis(
            session,
            tenant_id=principal.tenant_id,
            event_id=event_id,
            summary=result.summary,
            provider=result.provider,
            confidence=result.confidence,
            evidence_refs=[item.model_dump() for item in result.evidence],
        )
        await append_audit(
            session,
            request,
            action="ai.analysis.completed",
            resource_type="event",
            outcome="success",
            principal=principal,
            project_id=completed_context.project_id,
            resource_id=str(completed_context.id),
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
    await require_registered_runbook_names(
        session, tenant_id=tenant_id, names=result.recommended_runbooks
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
