#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

deployment_root=/home/qyy/aiops-x
server_address=
apply=false

usage() {
  cat <<'EOF'
Usage: initialize-test-environment.sh --server-address IP_OR_DNS [options]

Options:
  --root PATH   Persistent deployment root.
  --apply       Create shared/.env and the Alertmanager token file.
  --help        Show this help.

The command is only for a new test deployment. It generates random values and
never prints them. It refuses to overwrite an existing shared environment,
token file, or unknown content under shared/. PKI is generated separately by
install-release.sh after artifact validation.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-address)
      server_address=$2
      shift 2
      ;;
    --root)
      deployment_root=$2
      shift 2
      ;;
    --apply)
      apply=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      deployment_fail "unknown argument: $1"
      ;;
  esac
done

if [[ -z "$server_address" ]]; then
  usage >&2
  deployment_fail "server address is required"
fi
validate_ipv4_address "$server_address"
validate_deployment_root "$deployment_root"
if ! command -v openssl >/dev/null 2>&1; then
  deployment_fail "openssl is required"
fi

environment_file="$deployment_root/shared/.env"
alertmanager_token_file="$deployment_root/shared/alertmanager-webhook-token"
if [[ -e "$environment_file" || -e "$alertmanager_token_file" ]]; then
  deployment_fail "shared environment or Alertmanager token already exists; refusing overwrite"
fi
if [[ "$apply" != true ]]; then
  deployment_log "validation passed; --apply would initialize $deployment_root/shared"
  exit 0
fi

umask 077
mkdir -p \
  "$deployment_root/releases" \
  "$deployment_root/backups" \
  "$deployment_root/shared/vault/state"
postgres_password=$(openssl rand -hex 24)
redis_password=$(openssl rand -hex 24)
minio_password=$(openssl rand -hex 24)
minio_api_password=$(openssl rand -hex 24)
minio_worker_password=$(openssl rand -hex 24)
grafana_password=$(openssl rand -hex 24)
jwt_secret=$(openssl rand -hex 48)
bootstrap_token=$(openssl rand -hex 32)
alertmanager_token=$(openssl rand -hex 32)

temporary_environment="$environment_file.incoming.$(date -u '+%Y%m%dT%H%M%SZ')"
cat >"$temporary_environment" <<EOF
COMPOSE_PROJECT_NAME=aiops-x-enterprise
AIOPS_WEB_BIND=$server_address
AIOPS_AGENT_BIND=$server_address
AIOPS_PKI_DIR=$deployment_root/shared/pki
AIOPS_WORKER_CONCURRENCY=2
POSTGRES_IMAGE=postgres:16.4-bookworm
PGVECTOR_BUILDER_IMAGE=gcc:13.3.0-bookworm
PYTHON_IMAGE=python:3.12.4-slim
NODE_IMAGE=node:22.22.0-alpine
NGINX_IMAGE=nginx:1.27.0-alpine
GO_IMAGE=golang:1.24.6-alpine
ALPINE_IMAGE=alpine:3.20.2
REDIS_IMAGE=redis:7.2.5-alpine
NATS_IMAGE=nats:2.10.17-alpine
MINIO_IMAGE=minio/minio:RELEASE.2024-06-29T01-20-47Z
MINIO_MC_IMAGE=minio/mc:RELEASE.2024-06-29T19-08-46Z
PROMETHEUS_IMAGE=quay.io/prometheus/prometheus:v2.53.1
ALERTMANAGER_IMAGE=quay.io/prometheus/alertmanager:v0.27.0
NODE_EXPORTER_IMAGE=quay.io/prometheus/node-exporter:v1.8.1
LOKI_IMAGE=grafana/loki:3.1.0
TEMPO_IMAGE=grafana/tempo:2.5.0
GRAFANA_IMAGE=grafana/grafana:11.1.0
OTEL_COLLECTOR_IMAGE=otel/opentelemetry-collector-contrib:0.105.0
PYPI_INDEX_URL=https://pypi.org/simple
NPM_REGISTRY=https://registry.npmjs.org
POSTGRES_DB=aiops_x
POSTGRES_USER=aiops_x
POSTGRES_PASSWORD=$postgres_password
REDIS_PASSWORD=$redis_password
MINIO_ROOT_USER=aiops_x_test
MINIO_ROOT_PASSWORD=$minio_password
MINIO_API_USER=aiops_x_api
MINIO_API_PASSWORD=$minio_api_password
MINIO_WORKER_USER=aiops_x_worker
MINIO_WORKER_PASSWORD=$minio_worker_password
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=$grafana_password
AIOPS_ENVIRONMENT=test
AIOPS_LOG_LEVEL=INFO
AIOPS_DATABASE_URL=postgresql+asyncpg://aiops_x:$postgres_password@postgres:5432/aiops_x
AIOPS_REDIS_URL=redis://:$redis_password@redis:6379/0
AIOPS_NATS_URL=nats://nats:4222
AIOPS_MINIO_ENDPOINT=minio:9000
AIOPS_MINIO_SECURE=false
AIOPS_MINIO_ACCESS_KEY=aiops_x_api
AIOPS_MINIO_SECRET_KEY=$minio_api_password
AIOPS_REPORT_BUCKET=aiops-reports
AIOPS_AUDIT_ARCHIVE_BUCKET=aiops-audit-worm
AIOPS_AUDIT_RETENTION_DAYS=2555
AIOPS_SECRET_PROVIDER=vault
AIOPS_VAULT_ADDR=http://vault:8200
AIOPS_VAULT_TOKEN_FILE=/run/vault/vault-token
AIOPS_VAULT_TOKEN_HOST_FILE=$deployment_root/shared/vault/vault-token
AIOPS_VAULT_STATE_DIR=$deployment_root/shared/vault/state
AIOPS_VAULT_KV_MOUNT=kv
AIOPS_OUTBOUND_ALLOWED_HOSTS=[]
AIOPS_JWT_SECRET=$jwt_secret
AIOPS_BOOTSTRAP_TOKEN=$bootstrap_token
AIOPS_ACCESS_TOKEN_TTL_SECONDS=900
AIOPS_REFRESH_TOKEN_TTL_SECONDS=604800
AIOPS_LOGIN_MAX_FAILURES=5
AIOPS_LOGIN_LOCK_SECONDS=900
AIOPS_OIDC_ENABLED=false
AIOPS_OIDC_ISSUER_URL=
AIOPS_OIDC_CLIENT_ID=
AIOPS_OIDC_CLIENT_SECRET=
AIOPS_OIDC_REDIRECT_URI=http://$server_address:8080/api/v1/auth/oidc/callback
AIOPS_OIDC_SCOPES=openid profile email
AIOPS_OIDC_AUTO_PROVISION=false
AIOPS_OIDC_DEFAULT_ROLE_NAMES=[]
AIOPS_ABAC_ENFORCED=false
AIOPS_AUTH_RATE_LIMIT_PER_MINUTE=30
AIOPS_API_RATE_LIMIT_PER_MINUTE=600
AIOPS_AGENT_CERTIFICATE_TTL_HOURS=24
AIOPS_AGENT_CERTIFICATE_RENEWAL_WINDOW_HOURS=8
AIOPS_ALERTMANAGER_WEBHOOK_TOKEN=$alertmanager_token
AIOPS_ALERTMANAGER_TOKEN_FILE=$alertmanager_token_file
AIOPS_ALERT_CORRELATION_WINDOW_SECONDS=900
AIOPS_AGENT_CONTROL_PLANE_URL=https://agent-gateway:8443
AIOPS_REGISTRATION_TOKEN=
AIOPS_HEARTBEAT_INTERVAL=15s
AIOPS_TASK_POLL_INTERVAL=5s
AIOPS_CERTIFICATE_RENEW_BEFORE=6h
AIOPS_AI_PROVIDER=
AIOPS_AI_API_KEY=
AIOPS_AI_BASE_URL=https://api.openai.com/v1
AIOPS_AI_MODEL=gpt-4.1-mini
AIOPS_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
AIOPS_OTEL_SERVICE_NAME=aiops-x-api
AIOPS_CORS_ORIGINS=["http://$server_address:8080"]
VITE_API_BASE_URL=/api
EOF
chmod 0600 "$temporary_environment"
printf '%s' "$alertmanager_token" >"$alertmanager_token_file"
chmod 0600 "$alertmanager_token_file"
touch "$deployment_root/shared/vault/vault-token"
chmod 0600 "$deployment_root/shared/vault/vault-token"
mv "$temporary_environment" "$environment_file"

deployment_log "test environment initialized without printing generated secrets"
deployment_log "shared environment: $environment_file"
deployment_log "next step: run remote-preflight.sh before install-release.sh, then bootstrap-vault.sh"
