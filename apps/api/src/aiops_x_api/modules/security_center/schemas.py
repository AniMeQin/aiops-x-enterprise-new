from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VulnerabilityInput(BaseModel):
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    cvss_vector: str | None = Field(default=None, max_length=255)
    affected_component: str | None = Field(default=None, max_length=255)
    affected_version: str | None = Field(default=None, max_length=120)
    fixed_version: str | None = Field(default=None, max_length=120)


class RemediationInput(BaseModel):
    recommendation: str = Field(default="", max_length=10_000)
    owner_id: UUID | None = None
    due_at: datetime | None = None


class RiskInput(BaseModel):
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)


class TicketInput(BaseModel):
    system: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=160)
    external_url: str | None = Field(default=None, max_length=512)
    status: str = Field(default="open", min_length=1, max_length=32)


class FindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    asset_id: UUID | None = None
    integration_id: UUID | None = None
    source: str = Field(min_length=1, max_length=80)
    external_id: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=20_000)
    severity: Literal["info", "low", "medium", "high", "critical"]
    cve_ids: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=200)
    raw_data_ref: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    vulnerability: VulnerabilityInput | None = None
    remediation: RemediationInput | None = None
    risk: RiskInput
    ticket: TicketInput | None = None


class FindingStatusUpdate(BaseModel):
    status: Literal["open", "triaged", "remediating", "resolved", "accepted", "false_positive"]
    reason: str = Field(min_length=3, max_length=500)


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    finding_id: str
    project_id: UUID
    asset_id: UUID | None
    integration_id: UUID | None
    source: str
    external_id: str
    fingerprint: str
    category: str
    title: str
    description: str
    severity: str
    status: str
    cve_ids: list[str]
    evidence_ids: list[str]
    raw_data_ref: str | None
    metadata_json: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FindingPage(BaseModel):
    items: list[FindingResponse]
    page: int
    page_size: int
    total: int


class VulnerabilityResponse(VulnerabilityInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class RemediationResponse(RemediationInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    change_id: UUID | None


class RiskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    likelihood: int
    impact: int
    score: int
    accepted: bool
    accepted_by: UUID | None
    acceptance_reason: str | None


class TicketResponse(TicketInput):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class FindingDetail(FindingResponse):
    vulnerability: VulnerabilityResponse | None
    remediation: RemediationResponse | None
    risk: RiskResponse
    ticket: TicketResponse | None
