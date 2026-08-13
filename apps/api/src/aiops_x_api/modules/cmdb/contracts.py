from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AssetView:
    id: UUID
    tenant_id: UUID
    project_id: UUID
    asset_id: str
    asset_type: str
    name: str
    hostname: str | None
    ip_addresses: list[str]
    environment: str
    criticality: str
    gxp_classification: str
    tags: list[str]
    lifecycle_status: str
    agent_status: str
    monitoring_status: str
