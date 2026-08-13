from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    parent_id: UUID | None = None


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    name: str
    description: str
    created_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    department_id: UUID | None = None


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    department_id: UUID | None
    name: str
    description: str
    created_at: datetime


class MembershipUpdate(BaseModel):
    user_ids: list[UUID] = Field(max_length=500)


class ProjectMembershipCreate(BaseModel):
    project_id: UUID
    subject_type: Literal["user", "group"]
    subject_id: UUID
    access_level: Literal["viewer", "operator", "approver", "manager"]
    environment_constraints: list[str] = Field(default_factory=list, max_length=50)
    asset_tag_constraints: list[str] = Field(default_factory=list, max_length=100)
    gxp_access: bool = False


class ProjectMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    subject_type: str
    subject_id: UUID
    access_level: str
    environment_constraints: list[str]
    asset_tag_constraints: list[str]
    gxp_access: bool
    created_by: UUID
    created_at: datetime


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    permissions: list[str] = Field(min_length=1, max_length=100)
    project_ids: list[UUID] = Field(default_factory=list, max_length=100)
    expires_at: datetime


class ApiTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    token_id: str
    tenant_id: UUID
    name: str
    token_prefix: str
    permissions: list[str]
    project_ids: list[str]
    created_by: UUID
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiTokenIssued(ApiTokenResponse):
    token: str


class OidcStatus(BaseModel):
    enabled: bool
    issuer: str | None
    client_id: str | None
    message: str


class OidcAuthorizationResponse(BaseModel):
    authorization_url: str
    expires_at: datetime
