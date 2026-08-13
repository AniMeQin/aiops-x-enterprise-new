from uuid import UUID

from pydantic import BaseModel, Field


class Hypothesis(BaseModel):
    hypothesis_id: str
    description: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_refs: list[str]
    contradicting_evidence_refs: list[str]
    verification_steps: list[str]


class EvidenceCitation(BaseModel):
    evidence_ref: str
    reason: str


class AIAnalysis(BaseModel):
    status: str
    provider: str | None = None
    summary: str
    impact: str
    hypotheses: list[Hypothesis]
    evidence: list[EvidenceCitation]
    confidence: float = Field(ge=0, le=1)
    missing_data: list[str]
    recommended_actions: list[str]
    recommended_runbooks: list[str]
    risk_notes: list[str]
    rollback_considerations: list[str]


class AIStatus(BaseModel):
    status: str
    configured: bool
    provider: str | None
    message: str


class AIAssistantQuery(BaseModel):
    project_id: UUID
    question: str = Field(min_length=2, max_length=4000)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=100)


class AIAssistantAnswer(BaseModel):
    status: str
    provider: str | None = None
    answer: str
    citations: list[str]
    confidence: float = Field(ge=0, le=1)
    missing_data: list[str]
    suggested_queries: list[str]
    risk_notes: list[str]
