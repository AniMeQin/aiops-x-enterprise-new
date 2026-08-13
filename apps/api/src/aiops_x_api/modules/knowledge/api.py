import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.knowledge.application import (
    document_visible,
    get_document_in_scope,
    human_document_id,
)
from aiops_x_api.modules.knowledge.infrastructure.models import KnowledgeChunk, KnowledgeDocument
from aiops_x_api.modules.knowledge.schemas import (
    KnowledgeChunkCreate,
    KnowledgeChunkResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentPage,
    KnowledgeDocumentResponse,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeVectorSearchRequest,
)
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents", response_model=KnowledgeDocumentPage)
async def list_documents(
    principal: Annotated[Principal, Depends(require_permission("knowledge:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
) -> KnowledgeDocumentPage:
    filters = [KnowledgeDocument.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(
            or_(
                KnowledgeDocument.project_id.in_(allowed_project_ids),
                KnowledgeDocument.project_id.is_(None),
            )
        )
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(
            or_(KnowledgeDocument.project_id == project_id, KnowledgeDocument.project_id.is_(None))
        )
    if status:
        filters.append(KnowledgeDocument.status == status)
    candidates = (
        await session.scalars(
            select(KnowledgeDocument)
            .where(*filters)
            .order_by(KnowledgeDocument.updated_at.desc())
            .limit(1000)
        )
    ).all()
    visible = [document for document in candidates if document_visible(document, principal)]
    start = (page - 1) * page_size
    return KnowledgeDocumentPage(
        items=[
            KnowledgeDocumentResponse.model_validate(row)
            for row in visible[start : start + page_size]
        ],
        page=page,
        page_size=page_size,
        total=len(visible),
    )


@router.post("/documents", response_model=KnowledgeDocumentResponse, status_code=201)
async def create_document(
    payload: KnowledgeDocumentCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("knowledge:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeDocumentResponse:
    if payload.project_id is not None:
        ensure_project_scope(principal, payload.project_id)
    elif "*" not in principal.permissions and "knowledge:tenant-write" not in principal.permissions:
        from aiops_x_api.core.errors import ApplicationError

        raise ApplicationError(
            code="AIOPS_2003", message="无权创建租户公共知识文档", status_code=403
        )
    async with session.begin():
        if payload.project_id is not None:
            await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
        document = KnowledgeDocument(
            document_id=human_document_id(),
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            document_type=payload.document_type,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            object_ref=payload.object_ref,
            mime_type=payload.mime_type,
            content_hash=payload.content_hash.lower(),
            classification=payload.classification,
            gxp_classification=payload.gxp_classification,
            allowed_role_names=sorted(set(payload.allowed_role_names)),
            tags=sorted(set(payload.tags)),
            metadata_json=payload.metadata,
            created_by=principal.user_id,
        )
        session.add(document)
        await session.flush()
        await append_audit(
            session,
            request,
            action="knowledge.document.registered",
            resource_type="knowledge_document",
            outcome="success",
            principal=principal,
            project_id=document.project_id,
            resource_id=str(document.id),
            metadata={
                "document_id": document.document_id,
                "classification": document.classification,
                "gxp_classification": document.gxp_classification,
            },
        )
    return KnowledgeDocumentResponse.model_validate(document)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    document_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("knowledge:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeDocumentResponse:
    document = await get_document_in_scope(session, principal=principal, document_id=document_id)
    if document.project_id is not None:
        ensure_project_scope(principal, document.project_id)
    return KnowledgeDocumentResponse.model_validate(document)


@router.post(
    "/documents/{document_id}/chunks",
    response_model=KnowledgeChunkResponse,
    status_code=201,
)
async def add_document_chunk(
    document_id: UUID,
    payload: KnowledgeChunkCreate,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("knowledge:index"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeChunkResponse:
    if hashlib.sha256(payload.content.encode("utf-8")).hexdigest() != payload.content_hash.lower():
        from aiops_x_api.core.errors import ApplicationError

        raise ApplicationError(
            code="AIOPS_8306",
            message="知识分块内容与 SHA-256 不匹配",
            status_code=422,
        )
    async with session.begin():
        document = await get_document_in_scope(
            session, principal=principal, document_id=document_id, require_visible=False
        )
        if document.project_id is not None:
            ensure_project_scope(principal, document.project_id)
        existing = await session.scalar(
            select(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document.id,
                KnowledgeChunk.chunk_index == payload.chunk_index,
            )
        )
        if existing is None:
            chunk = KnowledgeChunk(
                tenant_id=document.tenant_id,
                project_id=document.project_id,
                document_id=document.id,
                chunk_index=payload.chunk_index,
                heading=payload.heading.strip(),
                content=payload.content,
                content_hash=payload.content_hash.lower(),
                token_count=payload.token_count,
                embedding=payload.embedding,
                evidence_refs=payload.evidence_refs,
                metadata_json=payload.metadata,
            )
            session.add(chunk)
        else:
            chunk = existing
            chunk.heading = payload.heading.strip()
            chunk.content = payload.content
            chunk.content_hash = payload.content_hash.lower()
            chunk.token_count = payload.token_count
            chunk.embedding = payload.embedding
            chunk.evidence_refs = payload.evidence_refs
            chunk.metadata_json = payload.metadata
        document.status = "indexed"
        document.indexing_error = None
        document.indexed_at = datetime.now(UTC)
        await session.flush()
        await append_audit(
            session,
            request,
            action="knowledge.document.indexed",
            resource_type="knowledge_document",
            outcome="success",
            principal=principal,
            project_id=document.project_id,
            resource_id=str(document.id),
            metadata={
                "chunk_index": chunk.chunk_index,
                "embedding_present": chunk.embedding is not None,
            },
        )
    return KnowledgeChunkResponse.model_validate(chunk)


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("knowledge:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=2, max_length=500)],
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> KnowledgeSearchResponse:
    filters = [
        KnowledgeDocument.tenant_id == principal.tenant_id,
        KnowledgeDocument.status == "indexed",
        or_(
            KnowledgeChunk.content.ilike(f"%{q.strip()}%"),
            KnowledgeChunk.heading.ilike(f"%{q.strip()}%"),
        ),
    ]
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(
            or_(KnowledgeDocument.project_id == project_id, KnowledgeDocument.project_id.is_(None))
        )
    elif (allowed_project_ids := scoped_project_ids(principal)) is not None:
        filters.append(
            or_(
                KnowledgeDocument.project_id.in_(allowed_project_ids),
                KnowledgeDocument.project_id.is_(None),
            )
        )
    rows = (
        await session.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(*filters)
            .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeChunk.chunk_index)
            .limit(200)
        )
    ).all()
    visible = [
        (chunk, document) for chunk, document in rows if document_visible(document, principal)
    ]
    items = [
        KnowledgeSearchResult(
            document_id=document.id,
            document_number=document.document_id,
            title=document.title,
            chunk_id=chunk.id,
            heading=chunk.heading,
            excerpt=_excerpt(chunk.content, q),
            classification=document.classification,
            gxp_classification=document.gxp_classification,
            score=None,
            source_ref=document.source_ref,
            evidence_refs=chunk.evidence_refs,
        )
        for chunk, document in visible[:limit]
    ]
    await session.rollback()
    async with session.begin():
        await append_audit(
            session,
            request,
            action="knowledge.search.performed",
            resource_type="knowledge_search",
            outcome="success",
            principal=principal,
            project_id=project_id,
            metadata={"query_length": len(q), "result_count": len(items), "mode": "text"},
        )
    return KnowledgeSearchResponse(items=items, total=len(visible), retrieval_mode="text")


@router.post("/search/vector", response_model=KnowledgeSearchResponse)
async def search_knowledge_by_vector(
    payload: KnowledgeVectorSearchRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("knowledge:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeSearchResponse:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        from aiops_x_api.core.errors import ApplicationError

        raise ApplicationError(
            code="AIOPS_8310",
            message="向量检索仅在 PostgreSQL pgvector 数据库中可用",
            status_code=503,
        )
    filters = [
        KnowledgeDocument.tenant_id == principal.tenant_id,
        KnowledgeDocument.status == "indexed",
        KnowledgeChunk.embedding.is_not(None),
    ]
    if payload.project_id is not None:
        ensure_project_scope(principal, payload.project_id)
        filters.append(
            or_(
                KnowledgeDocument.project_id == payload.project_id,
                KnowledgeDocument.project_id.is_(None),
            )
        )
    elif (allowed_project_ids := scoped_project_ids(principal)) is not None:
        filters.append(
            or_(
                KnowledgeDocument.project_id.in_(allowed_project_ids),
                KnowledgeDocument.project_id.is_(None),
            )
        )
    distance = KnowledgeChunk.embedding.cosine_distance(payload.embedding).label("distance")
    rows = (
        await session.execute(
            select(KnowledgeChunk, KnowledgeDocument, distance)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(*filters)
            .order_by(distance)
            .limit(min(200, payload.limit * 5))
        )
    ).all()
    visible = [
        (chunk, document, float(raw_distance))
        for chunk, document, raw_distance in rows
        if document_visible(document, principal)
        and 1.0 - float(raw_distance) >= payload.minimum_score
    ]
    items = [
        KnowledgeSearchResult(
            document_id=document.id,
            document_number=document.document_id,
            title=document.title,
            chunk_id=chunk.id,
            heading=chunk.heading,
            excerpt=chunk.content[:440],
            classification=document.classification,
            gxp_classification=document.gxp_classification,
            score=max(-1.0, min(1.0, 1.0 - raw_distance)),
            source_ref=document.source_ref,
            evidence_refs=chunk.evidence_refs,
        )
        for chunk, document, raw_distance in visible[: payload.limit]
    ]
    await session.rollback()
    async with session.begin():
        await append_audit(
            session,
            request,
            action="knowledge.search.performed",
            resource_type="knowledge_search",
            outcome="success",
            principal=principal,
            project_id=payload.project_id,
            metadata={
                "embedding_dimensions": len(payload.embedding),
                "result_count": len(items),
                "mode": "vector",
            },
        )
    return KnowledgeSearchResponse(items=items, total=len(visible), retrieval_mode="vector")


def _excerpt(content: str, query: str, radius: int = 220) -> str:
    lowered = content.lower()
    position = lowered.find(query.strip().lower())
    if position < 0:
        return content[: radius * 2]
    start = max(0, position - radius)
    end = min(len(content), position + len(query) + radius)
    return content[start:end]
