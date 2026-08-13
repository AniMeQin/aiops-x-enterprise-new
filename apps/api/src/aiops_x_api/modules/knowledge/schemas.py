from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeDocumentCreate(BaseModel):
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    document_type: Literal[
        "sop", "runbook", "postmortem", "architecture", "vendor", "note", "other"
    ]
    source_type: Literal["upload", "minio", "url", "incident", "manual"]
    source_ref: str = Field(min_length=1, max_length=512)
    object_ref: str | None = Field(default=None, max_length=512)
    mime_type: str = Field(min_length=1, max_length=120)
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    gxp_classification: Literal["gxp", "non_gxp", "unclassified"] = "unclassified"
    allowed_role_names: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_ref", "object_ref")
    @classmethod
    def reject_inline_secrets(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        if any(marker in lowered for marker in ("password=", "token=", "secret=")):
            raise ValueError("knowledge references must not contain inline credentials")
        return value


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: str
    tenant_id: UUID
    project_id: UUID | None
    title: str
    description: str
    document_type: str
    source_type: str
    source_ref: str
    object_ref: str | None
    mime_type: str
    content_hash: str
    version: int
    status: str
    classification: str
    gxp_classification: str
    allowed_role_names: list[str]
    tags: list[str]
    metadata_json: dict[str, Any]
    indexing_error: str | None
    created_by: UUID
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentPage(BaseModel):
    items: list[KnowledgeDocumentResponse]
    page: int
    page_size: int
    total: int


class KnowledgeChunkCreate(BaseModel):
    chunk_index: int = Field(ge=0)
    heading: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=50000)
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    token_count: int = Field(ge=1, le=50000)
    embedding: list[float] | None = Field(default=None, min_length=1536, max_length=1536)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    chunk_index: int
    heading: str
    content: str
    content_hash: str
    token_count: int
    evidence_refs: list[str]
    metadata_json: dict[str, Any]
    created_at: datetime


class KnowledgeSearchResult(BaseModel):
    document_id: UUID
    document_number: str
    title: str
    chunk_id: UUID
    heading: str
    excerpt: str
    classification: str
    gxp_classification: str
    score: float | None
    source_ref: str
    evidence_refs: list[str]


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeSearchResult]
    total: int
    retrieval_mode: Literal["vector", "text"]


class KnowledgeVectorSearchRequest(BaseModel):
    project_id: UUID | None = None
    embedding: list[float] = Field(min_length=1536, max_length=1536)
    limit: int = Field(default=10, ge=1, le=50)
    minimum_score: float = Field(default=0.0, ge=-1.0, le=1.0)
