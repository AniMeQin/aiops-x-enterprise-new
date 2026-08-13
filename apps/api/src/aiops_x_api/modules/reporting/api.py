import hashlib
import html
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit
from aiops_x_api.modules.identity.security import (
    Principal,
    ensure_project_scope,
    require_permission,
    scoped_project_ids,
)
from aiops_x_api.modules.incident.application import incident_report_data
from aiops_x_api.modules.reporting.infrastructure.models import GeneratedReport
from aiops_x_api.modules.reporting.schemas import ReportGenerateRequest, ReportPage, ReportResponse
from aiops_x_api.modules.reporting.storage import get_report, put_report
from aiops_x_api.modules.tenant.application import get_project_in_tenant

router = APIRouter(prefix="/reports", tags=["reporting"])


@router.get("", response_model=ReportPage)
async def list_reports(
    principal: Annotated[Principal, Depends(require_permission("report:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: Annotated[UUID | None, Query()] = None,
) -> ReportPage:
    filters = [GeneratedReport.tenant_id == principal.tenant_id]
    allowed_project_ids = scoped_project_ids(principal)
    if allowed_project_ids is not None:
        filters.append(GeneratedReport.project_id.in_(allowed_project_ids))
    if project_id is not None:
        ensure_project_scope(principal, project_id)
        filters.append(GeneratedReport.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(GeneratedReport).where(*filters))
    rows = (
        await session.scalars(
            select(GeneratedReport)
            .where(*filters)
            .order_by(GeneratedReport.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ReportPage(
        items=[ReportResponse.model_validate(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post("/generate", response_model=ReportResponse, status_code=201)
async def generate_report(
    payload: ReportGenerateRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("report:generate"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportResponse:
    ensure_project_scope(principal, payload.project_id)
    await get_project_in_tenant(session, principal.tenant_id, payload.project_id)
    source_data = await incident_report_data(
        session,
        tenant_id=principal.tenant_id,
        project_id=payload.project_id,
        incident_id=payload.source_id,
    )
    report_number = f"RPT-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"
    content, content_type, extension = _render_report(payload.title, source_data, payload.format)
    content_hash = hashlib.sha256(content).hexdigest()
    object_name = (
        f"tenant/{principal.tenant_id}/project/{payload.project_id}/"
        f"{datetime.now(UTC):%Y/%m}/{report_number}.{extension}"
    )
    await session.rollback()
    object_ref = await put_report(
        object_name=object_name, content=content, content_type=content_type
    )
    generated_at = datetime.now(UTC)
    async with session.begin():
        report = GeneratedReport(
            report_id=report_number,
            tenant_id=principal.tenant_id,
            project_id=payload.project_id,
            report_type=payload.report_type,
            title=payload.title.strip(),
            source_type="incident",
            source_id=payload.source_id,
            format=payload.format,
            status="completed",
            object_ref=object_ref,
            content_type=content_type,
            content_hash=content_hash,
            size_bytes=len(content),
            generation_metadata={
                "renderer": "aiops-x-reporting-v1",
                "evidence_first": True,
                "source_snapshot_at": generated_at.isoformat(),
            },
            created_by=principal.user_id,
            generated_at=generated_at,
        )
        session.add(report)
        await session.flush()
        await append_audit(
            session,
            request,
            action="report.generated",
            resource_type="report",
            outcome="success",
            principal=principal,
            project_id=report.project_id,
            resource_id=str(report.id),
            metadata={
                "report_id": report.report_id,
                "report_type": report.report_type,
                "content_hash": report.content_hash,
                "size_bytes": report.size_bytes,
            },
        )
    return ReportResponse.model_validate(report)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report_metadata(
    report_id: UUID,
    principal: Annotated[Principal, Depends(require_permission("report:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportResponse:
    report = await _get_report_row(session, principal.tenant_id, report_id)
    ensure_project_scope(principal, report.project_id)
    return ReportResponse.model_validate(report)


@router.get("/{report_id}/content")
async def download_report(
    report_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission("report:download"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    report = await _get_report_row(session, principal.tenant_id, report_id)
    ensure_project_scope(principal, report.project_id)
    downloaded_report_id = report.id
    downloaded_project_id = report.project_id
    object_ref = report.object_ref
    expected_hash = report.content_hash
    report_number = report.report_id
    content_type = report.content_type
    format_name = report.format
    content = await get_report(object_ref)
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ApplicationError(
            code="AIOPS_8605",
            message="报告完整性校验失败，已阻止下载",
            status_code=409,
        )
    await session.rollback()
    async with session.begin():
        await append_audit(
            session,
            request,
            action="report.downloaded",
            resource_type="report",
            outcome="success",
            principal=principal,
            project_id=downloaded_project_id,
            resource_id=str(downloaded_report_id),
            metadata={"report_id": report_number},
        )
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{report_number}.{format_name}"'},
    )


async def _get_report_row(
    session: AsyncSession, tenant_id: UUID, report_id: UUID
) -> GeneratedReport:
    report = await session.scalar(
        select(GeneratedReport).where(
            GeneratedReport.id == report_id, GeneratedReport.tenant_id == tenant_id
        )
    )
    if report is None:
        raise ApplicationError(code="AIOPS_8604", message="报告不存在", status_code=404)
    return report


def _render_report(
    title: str, source_data: dict[str, Any], format_name: str
) -> tuple[bytes, str, str]:
    payload = {
        "schema": "aiops-x.report.v1",
        "title": title,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source_data,
    }
    if format_name == "json":
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
            "application/json; charset=utf-8",
            "json",
        )
    escaped_title = html.escape(title)
    escaped_json = html.escape(
        json.dumps(source_data, ensure_ascii=False, indent=2, sort_keys=True)
    )
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{escaped_title}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;"
        "line-height:1.6;color:#172033}h1{border-bottom:2px solid #4065d6;padding-bottom:12px}"
        "pre{white-space:pre-wrap;background:#f5f7fb;padding:20px;border-radius:8px}</style>"
        f"</head><body><h1>{escaped_title}</h1><pre>{escaped_json}</pre></body></html>"
    )
    return document.encode("utf-8"), "text/html; charset=utf-8", "html"
