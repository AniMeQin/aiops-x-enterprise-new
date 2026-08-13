from aiops_x_api.core.database import Base
from aiops_x_api.development.seed import (
    TEST_ASSET_CREDENTIAL_REF,
    seed_verified_test_asset,
)
from aiops_x_api.modules.audit.infrastructure.models import AuditLog
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.identity.infrastructure.models import (  # noqa: F401
    AuthSession,
    Role,
    User,
    UserRole,
)
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def test_development_seed_is_entity_idempotent_and_never_stores_a_password() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session, session.begin():
        first = await seed_verified_test_asset(session)
    async with session_factory() as session, session.begin():
        second = await seed_verified_test_asset(session)

    async with session_factory() as session:
        asset = await session.scalar(select(Asset))
        asset_count = await session.scalar(select(func.count()).select_from(Asset))
        tenant_count = await session.scalar(select(func.count()).select_from(Tenant))
        project_count = await session.scalar(select(func.count()).select_from(Project))
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))

    assert asset is not None
    assert first.asset_id == second.asset_id == asset.id
    assert asset_count == tenant_count == project_count == 1
    assert audit_count == 2
    assert asset.ip_addresses == ["10.1.12.96"]
    assert asset.custom_attributes["ssh"] == {"port": 22, "username": "qyy"}
    assert asset.credential_ref == TEST_ASSET_CREDENTIAL_REF
    assert asset.monitoring_status == "not_configured"
    assert asset.custom_attributes["connection_verification"]["current_status"] == "not_checked"
    assert "password" not in json_text(asset.custom_attributes).lower()
    assert "animefox" not in json_text(asset.custom_attributes).lower()
    await engine.dispose()


def json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
