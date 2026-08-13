from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TopologyNode(BaseModel):
    id: UUID
    asset_id: str
    project_id: UUID
    name: str
    asset_type: str
    criticality: str
    gxp_classification: str
    lifecycle_status: str
    agent_status: str
    monitoring_status: str
    environment: str


class TopologyEdge(BaseModel):
    id: UUID
    source_asset_id: UUID
    target_asset_id: UUID
    relation_type: str
    source: str
    confidence: str
    manually_confirmed: bool


class TopologyResponse(BaseModel):
    generated_at: datetime
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
