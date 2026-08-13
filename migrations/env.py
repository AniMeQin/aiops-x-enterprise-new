from logging.config import fileConfig

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base
from aiops_x_api.modules.agent_control.infrastructure.models import (  # noqa: F401
    AgentRegistrationToken,
    AgentTask,
    EdgeAgent,
)
from aiops_x_api.modules.audit.infrastructure.models import AuditLog, EventOutbox  # noqa: F401
from aiops_x_api.modules.automation.infrastructure.models import (  # noqa: F401
    ApprovalDecision,
    ApprovalRequest,
    AutomationJob,
    Runbook,
    RunbookVersion,
)
from aiops_x_api.modules.change.infrastructure.models import (  # noqa: F401
    ChangeApprovalDecision,
    ChangeRequest,
    ChangeTimelineEntry,
)
from aiops_x_api.modules.cmdb.infrastructure.models import Asset, AssetRelation  # noqa: F401
from aiops_x_api.modules.discovery.infrastructure.models import (  # noqa: F401
    DiscoveryCandidate,
    DiscoveryJob,
    DiscoveryRun,
)
from aiops_x_api.modules.evidence.infrastructure.models import EvidenceRecord  # noqa: F401
from aiops_x_api.modules.identity.infrastructure.models import (  # noqa: F401
    ApiToken,
    AuthSession,
    Department,
    GroupMembership,
    IdentityGroup,
    OidcAuthorizationState,
    OidcIdentity,
    ProjectMembership,
    Role,
    User,
    UserDepartment,
    UserRole,
)
from aiops_x_api.modules.incident.infrastructure.models import (  # noqa: F401
    Incident,
    IncidentPostmortem,
    IncidentTimelineEntry,
)
from aiops_x_api.modules.integrations.infrastructure.models import Integration  # noqa: F401
from aiops_x_api.modules.knowledge.infrastructure.models import (  # noqa: F401
    KnowledgeChunk,
    KnowledgeDocument,
)
from aiops_x_api.modules.monitoring.infrastructure.models import (  # noqa: F401
    AssetMonitorBinding,
    MonitorTarget,
)
from aiops_x_api.modules.operations.infrastructure.models import (  # noqa: F401
    Alert,
    EventAlert,
    EventTimelineEntry,
    MaintenanceWindow,
    OperationsEvent,
)
from aiops_x_api.modules.plugins.infrastructure.models import (  # noqa: F401
    PluginDefinition,
    PluginInvocation,
)
from aiops_x_api.modules.reliability.infrastructure.models import (  # noqa: F401
    CapacityAnalysis,
    ServiceLevelObjective,
    SloEvaluation,
)
from aiops_x_api.modules.reporting.infrastructure.models import GeneratedReport  # noqa: F401
from aiops_x_api.modules.security_center.infrastructure.models import (  # noqa: F401
    RemediationRecord,
    RiskRecord,
    SecurityFinding,
    SecurityTicket,
    VulnerabilityRecord,
)
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant  # noqa: F401
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.get_secret_value())
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
