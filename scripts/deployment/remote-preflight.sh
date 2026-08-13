#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

deployment_root=/home/qyy/aiops-x
release_directory=
agent_server_name=
failures=0

usage() {
  cat <<'EOF'
Usage: remote-preflight.sh [options]

Options:
  --root PATH          Persistent deployment root.
  --release-dir PATH   Extracted release directory to validate with Compose.
  --agent-server-name  Expected Agent Gateway certificate IP or DNS name.
  --help               Show this help.

This command is read-only. It never starts containers or modifies files.
EOF
}

preflight_pass() {
  printf 'PASS  %s\n' "$*"
}

preflight_warn() {
  printf 'WARN  %s\n' "$*"
}

preflight_fail() {
  printf 'FAIL  %s\n' "$*" >&2
  failures=$((failures + 1))
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      deployment_root=$2
      shift 2
      ;;
    --release-dir)
      release_directory=$2
      shift 2
      ;;
    --agent-server-name)
      agent_server_name=$2
      shift 2
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

validate_deployment_root "$deployment_root"

for command_name in awk curl df docker grep openssl python3 sed stat tar; do
  if command -v "$command_name" >/dev/null 2>&1; then
    preflight_pass "command available: $command_name"
  else
    preflight_fail "missing command: $command_name"
  fi
done

if [[ -r /etc/os-release ]]; then
  os_name=$(awk -F= '$1 == "PRETTY_NAME" {gsub(/^"|"$/, "", $2); print $2}' /etc/os-release)
  preflight_pass "operating system: ${os_name:-unknown}"
else
  preflight_warn "cannot read /etc/os-release"
fi

preflight_pass "architecture: $(uname -m)"
preflight_pass "CPU threads: $(getconf _NPROCESSORS_ONLN 2>/dev/null || printf 'unknown')"
if command -v free >/dev/null 2>&1; then
  memory_mib=$(free -m | awk '/^Mem:/ {print $2}')
  if [[ -n "$memory_mib" && "$memory_mib" -ge 4096 ]]; then
    preflight_pass "memory: ${memory_mib} MiB"
  else
    preflight_warn "memory below recommended 4096 MiB: ${memory_mib:-unknown} MiB"
  fi
fi

deployment_parent=$(dirname "$deployment_root")
if [[ -d "$deployment_root" ]]; then
  disk_probe=$deployment_root
elif [[ -d "$deployment_parent" ]]; then
  disk_probe=$deployment_parent
else
  disk_probe=/home
fi
available_kib=$(df -Pk "$disk_probe" | awk 'NR == 2 {print $4}')
if [[ -n "$available_kib" && "$available_kib" -ge 10485760 ]]; then
  preflight_pass "available disk: $((available_kib / 1024)) MiB"
else
  preflight_fail "less than 10 GiB available under $disk_probe"
fi

if docker info >/dev/null 2>&1; then
  preflight_pass "Docker daemon reachable"
else
  preflight_fail "Docker daemon is not reachable by the current user"
fi
if docker compose version >/dev/null 2>&1; then
  preflight_pass "Docker Compose v2 available"
else
  preflight_fail "Docker Compose v2 is unavailable"
fi

shared_environment="$deployment_root/shared/.env"
if [[ -f "$shared_environment" ]]; then
  environment_mode=$(file_mode "$shared_environment")
  if (( (8#$environment_mode & 077) == 0 )); then
    preflight_pass "shared environment file permissions: $environment_mode"
  else
    preflight_fail "shared environment file must not be group/world accessible: $environment_mode"
  fi

  required_variables='COMPOSE_PROJECT_NAME AIOPS_WEB_BIND AIOPS_AGENT_BIND POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_API_USER MINIO_API_PASSWORD MINIO_WORKER_USER MINIO_WORKER_PASSWORD GRAFANA_ADMIN_PASSWORD AIOPS_DATABASE_URL AIOPS_REDIS_URL AIOPS_NATS_URL AIOPS_MINIO_ENDPOINT AIOPS_MINIO_ACCESS_KEY AIOPS_MINIO_SECRET_KEY AIOPS_SECRET_PROVIDER AIOPS_VAULT_TOKEN_HOST_FILE AIOPS_JWT_SECRET AIOPS_BOOTSTRAP_TOKEN AIOPS_ALERTMANAGER_WEBHOOK_TOKEN AIOPS_CORS_ORIGINS'
  for variable_name in $required_variables; do
    if grep -Eq "^${variable_name}=.+" "$shared_environment"; then
      preflight_pass "environment variable present: $variable_name"
    else
      preflight_fail "environment variable missing or empty: $variable_name"
    fi
  done
  if grep -Eq '=(change-me|change_me|changeme|password|secret)(-|_|$)' "$shared_environment"; then
    preflight_fail "shared environment still contains a known placeholder value"
  else
    preflight_pass "no known placeholder values detected"
  fi
  if [[ -n "$agent_server_name" ]]; then
    agent_bind=$(environment_value "$shared_environment" AIOPS_AGENT_BIND)
    web_bind=$(environment_value "$shared_environment" AIOPS_WEB_BIND)
    cors_origins=$(environment_value "$shared_environment" AIOPS_CORS_ORIGINS)
    if [[ "$agent_bind" == "$agent_server_name" ]]; then
      preflight_pass "Agent Gateway bind matches the requested server address"
    else
      preflight_fail "AIOPS_AGENT_BIND does not match $agent_server_name"
    fi
    if [[ "$web_bind" == "$agent_server_name" ]]; then
      preflight_pass "Web bind matches the requested server address"
    else
      preflight_fail "AIOPS_WEB_BIND does not match $agent_server_name"
    fi
    if [[ "$cors_origins" == *"http://$agent_server_name:8080"* ]]; then
      preflight_pass "CORS contains the test Web origin"
    else
      preflight_fail "AIOPS_CORS_ORIGINS is missing http://$agent_server_name:8080"
    fi
  fi
else
  preflight_fail "missing shared environment file: $shared_environment"
fi

alertmanager_token_file="$deployment_root/shared/alertmanager-webhook-token"
if [[ -s "$alertmanager_token_file" ]]; then
  token_mode=$(file_mode "$alertmanager_token_file")
  if (( (8#$token_mode & 077) == 0 )); then
    preflight_pass "Alertmanager token file exists with private permissions"
  else
    preflight_fail "Alertmanager token file permissions are too broad: $token_mode"
  fi
else
  preflight_fail "missing Alertmanager token file: $alertmanager_token_file"
fi

required_pki_files='agent-ca-key.pem agent-ca-cert.pem agent-server-key.pem agent-server-cert.pem agent-task-signing-key.pem agent-task-signing-cert.pem'
pki_ready=true
for pki_file in $required_pki_files; do
  if [[ ! -s "$deployment_root/shared/pki/$pki_file" ]]; then
    pki_ready=false
  fi
done
if [[ "$pki_ready" == true ]]; then
  if [[ -n "$agent_server_name" ]] && \
      validate_agent_pki "$deployment_root/shared/pki" "$agent_server_name"; then
    preflight_pass "Agent PKI certificate chain, key pairs, validity, and SAN are valid"
  elif [[ -n "$agent_server_name" ]]; then
    preflight_fail "Agent PKI validation failed"
  else
    preflight_warn "Agent PKI is complete but SAN validation needs --agent-server-name"
  fi
else
  preflight_warn "Agent PKI is incomplete; first release install must generate it"
fi

if [[ -n "$release_directory" ]]; then
  release_directory=$(cd "$release_directory" && pwd)
  if [[ ! -f "$release_directory/compose.yaml" ]]; then
    preflight_fail "release directory is missing compose.yaml"
  elif [[ -f "$shared_environment" ]]; then
    if run_release_compose "$release_directory" "$deployment_root" config --quiet; then
      service_count=$(run_release_compose "$release_directory" "$deployment_root" config --services | wc -l)
      preflight_pass "Compose configuration resolves successfully ($service_count services)"
    else
      preflight_fail "Compose configuration does not resolve"
    fi
  fi
fi

if command -v ss >/dev/null 2>&1; then
  for port in 8080 8443; do
    if ss -lnt | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
      preflight_warn "TCP port $port is already listening; verify it belongs to the existing AIOps-X release"
    else
      preflight_pass "TCP port $port is currently free"
    fi
  done
fi

if [[ $failures -gt 0 ]]; then
  deployment_fail "preflight completed with $failures failure(s)"
fi
preflight_pass "preflight completed without failures"
