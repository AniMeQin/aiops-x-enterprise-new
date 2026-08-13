from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantScope:
    id: UUID
    slug: str
    status: str


@dataclass(frozen=True)
class ProjectScope:
    id: UUID
    tenant_id: UUID
    slug: str
    status: str
