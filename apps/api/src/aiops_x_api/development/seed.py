import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import get_session_factory
from aiops_x_api.modules.audit.infrastructure.models import AuditLog
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant

TEST_ASSET_IP = "10.1.12.96"
TEST_ASSET_VERIFIED_AT = datetime(2026, 8, 12, 4, 8, 2, tzinfo=UTC)
TEST_ASSET_CREDENTIAL_REF = "vault://kv/aiops-x/development/assets/kali-10-1-12-96/ssh"


@dataclass(frozen=True)
class SeedResult:
    tenant_id: UUID
    project_id: UUID
    asset_id: UUID
    asset_external_id: str
    credential_ref: str


async def seed_verified_test_asset(session: AsyncSession) -> SeedResult:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == "development"))
    if tenant is None:
        tenant = Tenant(name="AIOps-X Development", slug="development", status="active")
        session.add(tenant)
        await session.flush()

    project = await session.scalar(
        select(Project).where(
            Project.tenant_id == tenant.id,
            Project.slug == "authorized-test-environment",
        )
    )
    if project is None:
        project = Project(
            tenant_id=tenant.id,
            name="授权测试环境",
            slug="authorized-test-environment",
            status="active",
        )
        session.add(project)
        await session.flush()

    external_id = "DEV-LINUX-10-1-12-96"
    asset = await session.scalar(
        select(Asset).where(
            Asset.tenant_id == tenant.id,
            Asset.asset_id == external_id,
        )
    )
    values = {
        "project_id": project.id,
        "asset_type": "linux",
        "name": "Kali SSH 测试设备",
        "hostname": "kali",
        "ip_addresses": [TEST_ASSET_IP],
        "operating_system": "Kali Linux",
        "environment": "development",
        "location": "authorized_test_environment",
        "criticality": "low",
        "gxp_classification": "unclassified",
        "lifecycle_status": "active",
        "agent_status": "not_installed",
        "monitoring_status": "not_configured",
        "credential_ref": TEST_ASSET_CREDENTIAL_REF,
        "tags": ["development", "authorized-test-device", "ssh"],
        "custom_attributes": {
            "ssh": {
                "port": 22,
                "username": "qyy",
            },
            "connection_verification": {
                "status": "historical_verified",
                "current_status": "not_checked",
                "verified_at": TEST_ASSET_VERIFIED_AT.isoformat().replace("+00:00", "Z"),
                "method": "interactive_ssh_authentication",
                "remote_user": "qyy",
                "remote_hostname": "kali",
                "kernel": "Linux 7.0.12+kali-amd64",
                "architecture": "x86_64",
            },
        },
    }
    if asset is None:
        asset = Asset(
            asset_id=external_id,
            tenant_id=tenant.id,
            **values,
        )
        session.add(asset)
        await session.flush()
        audit_action = "development.asset.created"
    else:
        for field, value in values.items():
            setattr(asset, field, value)
        await session.flush()
        audit_action = "development.asset.refreshed"

    session.add(
        AuditLog(
            tenant_id=tenant.id,
            project_id=project.id,
            actor_type="system",
            actor_id="development-seed",
            action=audit_action,
            resource_type="asset",
            resource_id=str(asset.id),
            request_id=str(uuid4()),
            trace_id=str(uuid4()),
            outcome="success",
            metadata_json={
                "asset_external_id": external_id,
                "verification_status": "historical_verified",
                "current_status": "not_checked",
                "verified_at": TEST_ASSET_VERIFIED_AT.isoformat().replace("+00:00", "Z"),
                "credential_storage": "reference_only",
            },
        )
    )
    await session.flush()
    return SeedResult(
        tenant_id=tenant.id,
        project_id=project.id,
        asset_id=asset.id,
        asset_external_id=external_id,
        credential_ref=TEST_ASSET_CREDENTIAL_REF,
    )


async def run() -> None:
    settings = get_settings()
    if settings.environment.lower() != "development":
        raise RuntimeError("development seed is disabled outside the development environment")

    async with get_session_factory()() as session, session.begin():
        result = await seed_verified_test_asset(session)
    print(json.dumps(asdict(result), default=str, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())
