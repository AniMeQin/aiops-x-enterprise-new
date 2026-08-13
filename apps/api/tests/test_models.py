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
from aiops_x_api.modules.cmdb.infrastructure.models import Asset, AssetRelation  # noqa: F401
from aiops_x_api.modules.identity.infrastructure.models import (  # noqa: F401
    AuthSession,
    Role,
    User,
    UserRole,
)
from aiops_x_api.modules.integrations.infrastructure.models import Integration  # noqa: F401
from aiops_x_api.modules.operations.infrastructure.models import (  # noqa: F401
    Alert,
    EventAlert,
    EventTimelineEntry,
    MaintenanceWindow,
    OperationsEvent,
)
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant  # noqa: F401


def test_foundation_schema_contains_tenant_scoped_tables() -> None:
    expected = {
        "tenants",
        "projects",
        "users",
        "roles",
        "user_roles",
        "auth_sessions",
        "assets",
        "asset_relations",
        "audit_logs",
        "event_outbox",
        "agent_registration_tokens",
        "edge_agents",
        "agent_tasks",
        "alerts",
        "operations_events",
        "event_alerts",
        "event_timeline_entries",
        "maintenance_windows",
        "runbooks",
        "runbook_versions",
        "automation_jobs",
        "approval_requests",
        "approval_decisions",
        "integrations",
    }
    assert expected <= set(Base.metadata.tables)
    assert Base.metadata.tables["assets"].c.tenant_id.index is True
    assert Base.metadata.tables["audit_logs"].c.tenant_id.index is True
    edge_agent_columns = set(Base.metadata.tables["edge_agents"].c.keys())
    assert {
        "previous_certificate_serial",
        "previous_certificate_fingerprint",
        "previous_certificate_not_after",
        "last_renewal_csr_fingerprint",
    } <= edge_agent_columns
