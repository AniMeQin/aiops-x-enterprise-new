from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.identity.security import Principal
from aiops_x_api.modules.knowledge.infrastructure.models import KnowledgeDocument

CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


def human_document_id() -> str:
    return f"KBD-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"


def document_visible(document: KnowledgeDocument, principal: Principal) -> bool:
    if "*" in principal.permissions:
        return True
    if document.allowed_role_names and not set(document.allowed_role_names).intersection(
        principal.roles
    ):
        return False
    if (
        document.classification == "restricted"
        and "knowledge:restricted" not in principal.permissions
    ):
        return False
    if document.classification == "confidential" and not {
        "knowledge:confidential",
        "knowledge:restricted",
    }.intersection(principal.permissions):
        return False
    if document.gxp_classification == "gxp" and "knowledge:gxp" not in principal.permissions:
        return False
    return True


async def get_document_in_scope(
    session: AsyncSession,
    *,
    principal: Principal,
    document_id: UUID,
    require_visible: bool = True,
) -> KnowledgeDocument:
    document = await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == principal.tenant_id,
        )
    )
    if document is None or (require_visible and not document_visible(document, principal)):
        raise ApplicationError(code="AIOPS_8304", message="知识文档不存在", status_code=404)
    return document
