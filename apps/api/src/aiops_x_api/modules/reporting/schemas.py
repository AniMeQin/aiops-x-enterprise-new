from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportGenerateRequest(BaseModel):
    project_id: UUID
    report_type: Literal["incident_postmortem", "incident_timeline"]
    title: str = Field(min_length=1, max_length=255)
    source_id: UUID
    format: Literal["json", "html"] = "html"


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_id: str
    tenant_id: UUID
    project_id: UUID
    report_type: str
    title: str
    source_type: str
    source_id: UUID
    format: str
    status: str
    object_ref: str
    content_type: str
    content_hash: str
    size_bytes: int
    generation_metadata: dict[str, Any]
    error_message: str | None
    created_by: UUID
    generated_at: datetime
    created_at: datetime


class ReportPage(BaseModel):
    items: list[ReportResponse]
    page: int
    page_size: int
    total: int
