from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    service: str
    version: str


class DependencyStatus(BaseModel):
    name: str
    status: Literal["healthy", "unhealthy", "not_configured"]
    required: bool
    message: str


class SecuritySettings(BaseModel):
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    login_max_failures: int
    login_lock_seconds: int
    auth_rate_limit_per_minute: int
    api_rate_limit_per_minute: int
    agent_certificate_ttl_hours: int
    destructive_actions_enabled: bool = False
    abac_enforced: bool


class SystemInfo(BaseModel):
    service: str
    version: str
    environment: str
    database: Literal["connected", "unavailable"]
    ai: Literal["configured", "not_configured", "unavailable"]
    dependencies: list[DependencyStatus]
    security: SecuritySettings
