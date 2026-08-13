from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    project_id: UUID | None
    actor_type: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None
    request_id: str
    trace_id: str
    outcome: str
    metadata_json: dict[str, Any]
    sequence_no: int
    previous_hash: str
    entry_hash: str
    archived_at: datetime | None
    archive_object_ref: str | None
    created_at: datetime


class AuditLogPage(BaseModel):
    items: list[AuditLogResponse]
    page: int
    page_size: int
    total: int


class AuditIntegrityResponse(BaseModel):
    valid: bool
    checked_entries: int
    first_sequence: int | None
    last_sequence: int | None
    broken_sequence: int | None
    message: str
