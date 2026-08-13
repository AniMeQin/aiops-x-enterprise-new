from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EvidenceType = Literal[
    "metric",
    "log",
    "trace",
    "alert",
    "configuration",
    "topology",
    "health_check",
    "automation_result",
    "scan_finding",
    "attachment",
]
Classification = Literal["public", "internal", "confidential", "restricted"]
GxpClassification = Literal["gxp", "non_gxp", "unclassified"]


class EvidenceCreate(BaseModel):
    project_id: UUID
    asset_id: UUID | None = None
    evidence_type: EvidenceType
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="", max_length=5000)
    source_type: str = Field(min_length=1, max_length=64)
    source_ref: str = Field(min_length=1, max_length=512)
    object_ref: str | None = Field(default=None, max_length=512)
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    classification: Classification = "internal"
    gxp_classification: GxpClassification = "unclassified"
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ref", "object_ref")
    @classmethod
    def reject_inline_secrets(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        if any(marker in lowered for marker in ("password=", "token=", "secret=")):
            raise ValueError("evidence references must not contain inline credentials")
        return value


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    evidence_id: str
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID | None
    evidence_type: str
    title: str
    summary: str
    source_type: str
    source_ref: str
    object_ref: str | None
    content_hash: str
    classification: str
    gxp_classification: str
    observed_at: datetime
    metadata_json: dict[str, Any]
    created_by: UUID
    created_at: datetime


class EvidencePage(BaseModel):
    items: list[EvidenceResponse]
    page: int
    page_size: int
    total: int
