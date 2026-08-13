import asyncio
import json
import os
from typing import Any
from urllib.request import Request as UrlRequest

from aiops_x_api.core.outbound_http import open_without_redirect, validate_outbound_url
from aiops_x_api.core.telemetry import configure_fastapi_telemetry
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

from aiops_x_ai import __version__

AI_REQUESTS = Counter("aiops_x_ai_requests_total", "AI analysis requests by result.", ("status",))
AI_DURATION = Histogram("aiops_x_ai_request_duration_seconds", "AI analysis request latency.")


class AIStatus(BaseModel):
    status: str
    configured: bool
    provider: str | None
    message: str


class EvidenceEnvelope(BaseModel):
    evidence: dict[str, Any]


class AIAnalysis(BaseModel):
    status: str
    provider: str | None = None
    summary: str
    impact: str
    hypotheses: list[dict[str, Any]]
    evidence: list[dict[str, str]]
    confidence: float
    missing_data: list[str]
    recommended_actions: list[str]
    recommended_runbooks: list[str]
    risk_notes: list[str]
    rollback_considerations: list[str]


class AssistantEnvelope(BaseModel):
    question: str
    evidence: list[dict[str, Any]]


class AssistantAnswer(BaseModel):
    status: str
    provider: str | None = None
    answer: str
    citations: list[str]
    confidence: float
    missing_data: list[str]
    suggested_queries: list[str]
    risk_notes: list[str]


def provider_status() -> AIStatus:
    provider = os.getenv("AIOPS_AI_PROVIDER", "").strip()
    api_key = os.getenv("AIOPS_AI_API_KEY", "").strip()
    normalized_provider = provider.lower()
    configured = bool(provider and (api_key or normalized_provider == "local"))
    if not configured:
        return AIStatus(
            status="unavailable",
            configured=False,
            provider=provider or None,
            message="AI 服务未配置",
        )
    if normalized_provider not in {"openai", "openai-compatible", "minimax", "local"}:
        return AIStatus(
            status="unsupported",
            configured=False,
            provider=provider,
            message="AI Provider 适配器未启用",
        )
    return AIStatus(
        status="configured",
        configured=True,
        provider=provider,
        message="AI provider configuration is present; connectivity is not yet verified.",
    )


app = FastAPI(title="AIOps-X AI Engine", version=__version__, redoc_url=None)
configure_fastapi_telemetry(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "aiops-x-ai-engine", "version": __version__}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ok", "service": "aiops-x-ai-engine", "version": __version__}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/ai/status", response_model=AIStatus)
async def ai_status() -> AIStatus:
    return provider_status()


@app.post("/api/v1/ai/analyze", response_model=AIAnalysis)
async def analyze(payload: EvidenceEnvelope) -> AIAnalysis:
    status = provider_status()
    if not status.configured:
        AI_REQUESTS.labels("not_configured").inc()
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
            risk_notes=["AI 未配置，未生成推测性结论。"],
            rollback_considerations=[],
        )
    try:
        with AI_DURATION.time():
            document = await asyncio.to_thread(_call_provider, payload.evidence)
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        AI_REQUESTS.labels("failed").inc()
        raise HTTPException(
            status_code=503,
            detail={"code": "AIOPS_AI_PROVIDER_UNAVAILABLE", "message": "AI 服务调用失败"},
        ) from error
    document["status"] = "completed"
    document["provider"] = status.provider
    AI_REQUESTS.labels("completed").inc()
    return AIAnalysis.model_validate(document)


@app.post("/api/v1/ai/assistant", response_model=AssistantAnswer)
async def assistant(payload: AssistantEnvelope) -> AssistantAnswer:
    status = provider_status()
    if not status.configured:
        AI_REQUESTS.labels("not_configured").inc()
        return AssistantAnswer(
            status="not_configured",
            answer="AI 服务未配置",
            citations=[],
            confidence=0,
            missing_data=["AI provider configuration"],
            suggested_queries=[],
            risk_notes=["AI 未配置，平台未生成推测性回答。"],
        )
    try:
        with AI_DURATION.time():
            document = await asyncio.to_thread(
                _call_provider_structured,
                {"question": payload.question, "evidence": payload.evidence},
                _assistant_schema(),
                "aiops_assistant_answer",
                (
                    "You are an evidence-first AIOps assistant. Answer only from supplied "
                    "evidence and cite evidence_id values. State missing data. Never claim to "
                    "execute commands or expose credentials. Return the requested JSON schema."
                ),
            )
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        AI_REQUESTS.labels("failed").inc()
        raise HTTPException(
            status_code=503,
            detail={"code": "AIOPS_AI_PROVIDER_UNAVAILABLE", "message": "AI 服务调用失败"},
        ) from error
    document["status"] = "completed"
    document["provider"] = status.provider
    AI_REQUESTS.labels("completed").inc()
    return AssistantAnswer.model_validate(document)


def _call_provider(evidence: dict[str, Any]) -> dict[str, Any]:
    return _call_provider_structured(
        evidence,
        _analysis_schema(),
        "aiops_event_analysis",
        (
            "You are an evidence-first AIOps analyst. Use only supplied evidence. "
            "Never claim to execute commands. Recommendations are advisory and must "
            "reference registered runbooks. Return the requested JSON schema."
        ),
    )


def _call_provider_structured(
    evidence: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str,
    system_prompt: str,
) -> dict[str, Any]:
    provider = os.environ["AIOPS_AI_PROVIDER"].strip().lower()
    api_key = os.environ["AIOPS_AI_API_KEY"].strip()
    base_url = os.getenv("AIOPS_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("AIOPS_AI_MODEL", "gpt-4.1-mini").strip()
    if provider not in {"openai", "openai-compatible", "minimax", "local"}:
        raise ValueError("configured AI provider adapter is not enabled")
    if provider in {"openai", "openai-compatible"}:
        path = "/responses"
        body = _responses_request(model, system_prompt, evidence, schema, schema_name)
    else:
        path = "/chat/completions"
        body = _chat_completions_request(model, system_prompt, evidence, schema, schema_name)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = UrlRequest(  # noqa: S310 -- configured HTTPS provider URL
        base_url + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers=headers,
    )
    validate_outbound_url(base_url + path)
    with open_without_redirect(request, timeout=45) as response:
        result = json.loads(response.read(2_097_152))
    output_text = _provider_output_text(provider, result)

    if not isinstance(output_text, str):
        raise ValueError("provider response did not include output_text")
    parsed = json.loads(output_text)
    if not isinstance(parsed, dict):
        raise ValueError("provider output is not an object")
    return {str(key): value for key, value in parsed.items()}


def _responses_request(
    model: str,
    system_prompt: str,
    evidence: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }


def _chat_completions_request(
    model: str,
    system_prompt: str,
    evidence: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str = "ai_analysis",
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
    }


def _provider_output_text(provider: str, result: dict[str, Any]) -> str | None:
    if provider in {"minimax", "local"}:
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        return content if isinstance(content, str) else None
    output_text = result.get("output_text")
    if not isinstance(output_text, str):
        for item in result.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text")
                    break
    return output_text if isinstance(output_text, str) else None


def _analysis_schema() -> dict[str, Any]:
    hypothesis = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hypothesis_id": {"type": "string"},
            "description": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "supporting_evidence_refs": {"type": "array", "items": {"type": "string"}},
            "contradicting_evidence_refs": {"type": "array", "items": {"type": "string"}},
            "verification_steps": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "hypothesis_id",
            "description",
            "confidence",
            "supporting_evidence_refs",
            "contradicting_evidence_refs",
            "verification_steps",
        ],
    }
    properties: dict[str, Any] = {
        "summary": {"type": "string"},
        "impact": {"type": "string"},
        "hypotheses": {"type": "array", "items": hypothesis},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "evidence_ref": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["evidence_ref", "reason"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "missing_data": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "recommended_runbooks": {"type": "array", "items": {"type": "string"}},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
        "rollback_considerations": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _assistant_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "missing_data": {"type": "array", "items": {"type": "string"}},
        "suggested_queries": {"type": "array", "items": {"type": "string"}},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }
