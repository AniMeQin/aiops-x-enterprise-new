import base64
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.database import get_session
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.agent_control.infrastructure.models import EdgeAgent
from aiops_x_api.modules.agent_control.pki import (
    normalize_certificate_serial,
    verify_proxy_certificate,
)


@dataclass(frozen=True)
class AgentPrincipal:
    agent_id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    certificate_serial: str
    is_current_certificate: bool


async def get_current_agent(
    session: Annotated[AsyncSession, Depends(get_session)],
    verify_status: Annotated[str | None, Header(alias="X-SSL-Client-Verify")] = None,
    certificate_serial: Annotated[str | None, Header(alias="X-SSL-Client-Serial")] = None,
    escaped_certificate: Annotated[str | None, Header(alias="X-SSL-Client-Cert")] = None,
) -> AgentPrincipal:
    if verify_status != "SUCCESS" or not certificate_serial or not escaped_certificate:
        raise _unauthorized_agent()
    try:
        normalized_serial = normalize_certificate_serial(certificate_serial)
        agent = await session.scalar(
            select(EdgeAgent).where(
                or_(
                    EdgeAgent.certificate_serial == normalized_serial,
                    EdgeAgent.previous_certificate_serial == normalized_serial,
                )
            )
        )
        if agent is None or agent.status == "disabled":
            raise ValueError
        is_current = agent.certificate_serial == normalized_serial
        expected_fingerprint = (
            agent.certificate_fingerprint if is_current else agent.previous_certificate_fingerprint
        )
        certificate_not_after = (
            agent.certificate_not_after if is_current else agent.previous_certificate_not_after
        )
        if expected_fingerprint is None or certificate_not_after is None:
            raise ValueError
        decoded = urllib.parse.unquote(escaped_certificate)
        if "BEGIN CERTIFICATE" not in decoded:
            decoded = base64.b64decode(decoded, validate=True).decode()
        fingerprint = verify_proxy_certificate(decoded, normalized_serial)
        if fingerprint != expected_fingerprint:
            raise ValueError
        if _required_utc(certificate_not_after) <= datetime.now(UTC):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise _unauthorized_agent() from None
    principal = AgentPrincipal(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        project_id=agent.project_id,
        asset_id=agent.asset_id,
        certificate_serial=normalized_serial,
        is_current_certificate=is_current,
    )
    await session.rollback()
    return principal


def _unauthorized_agent() -> ApplicationError:
    return ApplicationError(
        code="AIOPS_4001", message="Agent 身份凭据无效或已过期", status_code=401
    )


def _required_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
