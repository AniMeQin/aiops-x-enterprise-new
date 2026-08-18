from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIOPS_",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://aiops_x:change-me-local-only@localhost:5432/aiops_x"
    )
    redis_url: SecretStr = SecretStr("redis://:change-me-local-only@localhost:6379/0")
    nats_url: str = "nats://localhost:4222"
    minio_endpoint: str = "localhost:9000"
    minio_secure: bool = False
    minio_access_key: SecretStr = SecretStr("change-me-development-minio")
    minio_secret_key: SecretStr = SecretStr("change-me-development-minio-secret")
    report_bucket: str = "aiops-reports"
    audit_archive_bucket: str = "aiops-audit-worm"
    audit_retention_days: int = Field(default=2555, ge=365, le=3650)
    secret_provider: str = "vault"  # noqa: S105 -- provider name, not a secret
    vault_addr: str = "http://vault:8200"
    vault_token_file: str = "/run/secrets/vault-token"  # noqa: S105 -- file path
    vault_namespace: str = ""
    vault_kv_mount: str = "kv"
    vault_timeout_seconds: int = Field(default=5, ge=1, le=30)
    outbound_allowed_hosts: list[str] = Field(default_factory=list)
    jwt_secret: SecretStr = SecretStr("change-me-development-jwt-secret-at-least-32-bytes")
    access_token_ttl_seconds: int = Field(default=900, ge=300, le=3600)
    refresh_token_ttl_seconds: int = Field(default=604800, ge=3600, le=2592000)
    bootstrap_token: SecretStr = SecretStr("change-me-development-bootstrap-token")
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_lock_seconds: int = Field(default=900, ge=60, le=86400)
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    oidc_redirect_uri: str = "http://localhost:8080/api/v1/auth/oidc/callback"
    oidc_scopes: str = "openid profile email"
    oidc_auto_provision: bool = False
    oidc_default_role_names: list[str] = Field(default_factory=list)
    abac_enforced: bool = False
    auth_rate_limit_per_minute: int = Field(default=30, ge=5, le=1000)
    api_rate_limit_per_minute: int = Field(default=600, ge=60, le=10000)
    agent_ca_key_path: str = "/run/secrets/agent-ca-key.pem"
    agent_ca_certificate_path: str = "/run/secrets/agent-ca-cert.pem"
    agent_server_certificate_path: str = "/run/secrets/agent-server-cert.pem"
    agent_server_key_path: str = "/run/secrets/agent-server-key.pem"
    agent_certificate_ttl_hours: int = Field(default=24, ge=1, le=168)
    agent_certificate_renewal_window_hours: int = Field(default=8, ge=1, le=72)
    agent_task_signing_key_path: str = "/run/secrets/agent-task-signing-key.pem"
    agent_task_signing_certificate_path: str = "/run/secrets/agent-task-signing-cert.pem"
    alertmanager_webhook_token: SecretStr = SecretStr("change-me-development-alertmanager-token")
    prometheus_url: str = "http://prometheus:9090"
    monitoring_sample_max_age_seconds: int = Field(default=90, ge=15, le=600)
    prometheus_target_file_path: str = "/var/lib/aiops-x/prometheus-targets/targets.json"
    prometheus_rule_file_path: str = "/var/lib/aiops-x/prometheus-rules/managed.json"
    prometheus_reload_url: str = "http://prometheus:9090/-/reload"
    loki_url: str = "http://loki:3100"
    tempo_url: str = "http://tempo:3200"
    alert_correlation_window_seconds: int = Field(default=900, ge=60, le=86400)
    ai_provider: str = ""
    ai_engine_url: str = "http://ai-engine:8001"
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "aiops-x-api"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8080", "http://localhost:5173"]
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
