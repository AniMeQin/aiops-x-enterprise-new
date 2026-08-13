#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

deployment_root=/home/qyy/aiops-x
apply=false

usage() {
  cat <<'EOF'
Usage: upgrade-shared-environment.sh [--root PATH] [--apply]

Adds only missing enterprise runtime variables to an existing protected test
environment. Existing values are preserved, a private backup is created, and
new service credentials are generated without printing them.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) deployment_root=$2; shift 2 ;;
    --apply) apply=true; shift ;;
    --help) usage; exit 0 ;;
    *) usage >&2; deployment_fail "unknown argument: $1" ;;
  esac
done

validate_deployment_root "$deployment_root"
environment_file="$deployment_root/shared/.env"
[[ -f "$environment_file" ]] || deployment_fail "shared environment does not exist"
command -v openssl >/dev/null 2>&1 || deployment_fail "openssl is required"
command -v python3 >/dev/null 2>&1 || deployment_fail "python3 is required"

required_names=(
  VAULT_IMAGE MINIO_MC_IMAGE MINIO_API_USER MINIO_API_PASSWORD
  MINIO_WORKER_USER MINIO_WORKER_PASSWORD AIOPS_MINIO_ACCESS_KEY
  AIOPS_MINIO_SECRET_KEY AIOPS_REPORT_BUCKET AIOPS_AUDIT_ARCHIVE_BUCKET
  AIOPS_AUDIT_RETENTION_DAYS AIOPS_SECRET_PROVIDER AIOPS_VAULT_ADDR
  AIOPS_VAULT_TOKEN_FILE AIOPS_VAULT_TOKEN_HOST_FILE AIOPS_VAULT_STATE_DIR
  AIOPS_VAULT_KV_MOUNT AIOPS_OUTBOUND_ALLOWED_HOSTS AIOPS_OIDC_ENABLED
  AIOPS_OIDC_ISSUER_URL AIOPS_OIDC_CLIENT_ID AIOPS_OIDC_CLIENT_SECRET
  AIOPS_OIDC_REDIRECT_URI AIOPS_OIDC_SCOPES AIOPS_OIDC_AUTO_PROVISION
  AIOPS_OIDC_DEFAULT_ROLE_NAMES AIOPS_ABAC_ENFORCED
)
missing=()
for name in "${required_names[@]}"; do
  grep -q "^${name}=" "$environment_file" || missing+=("$name")
done
if [[ ${#missing[@]} -eq 0 ]]; then
  deployment_log "shared environment already contains all enterprise variables"
  exit 0
fi
if [[ "$apply" != true ]]; then
  deployment_log "validation passed; ${#missing[@]} missing variable(s) would be added"
  exit 0
fi

umask 077
backup_directory="$deployment_root/backups/environment-upgrades"
mkdir -p "$backup_directory" "$deployment_root/shared/vault/state"
backup_path="$backup_directory/$(date -u '+%Y%m%dT%H%M%SZ').env"
cp -p "$environment_file" "$backup_path"
chmod 0600 "$backup_path"

minio_api_password=$(openssl rand -hex 24)
minio_worker_password=$(openssl rand -hex 24)
server_address=$(environment_value "$environment_file" AIOPS_WEB_BIND)
[[ -n "$server_address" ]] || deployment_fail "AIOPS_WEB_BIND is required"
temporary_file="$environment_file.incoming.$(date -u '+%Y%m%dT%H%M%SZ')"
python3 - "$environment_file" "$temporary_file" "$deployment_root" "$server_address" \
  "$minio_api_password" "$minio_worker_password" <<'PY'
import os
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
root = sys.argv[3]
server = sys.argv[4]
api_password = sys.argv[5]
worker_password = sys.argv[6]
existing = source.read_text().rstrip("\n")
names = {line.split("=", 1)[0] for line in existing.splitlines() if "=" in line}
values = {
    "VAULT_IMAGE": "hashicorp/vault:1.17.2",
    "MINIO_MC_IMAGE": "minio/mc:RELEASE.2024-06-29T19-08-46Z",
    "MINIO_API_USER": "aiops_x_api",
    "MINIO_API_PASSWORD": api_password,
    "MINIO_WORKER_USER": "aiops_x_worker",
    "MINIO_WORKER_PASSWORD": worker_password,
    "AIOPS_MINIO_ACCESS_KEY": "aiops_x_api",
    "AIOPS_MINIO_SECRET_KEY": api_password,
    "AIOPS_REPORT_BUCKET": "aiops-reports",
    "AIOPS_AUDIT_ARCHIVE_BUCKET": "aiops-audit-worm",
    "AIOPS_AUDIT_RETENTION_DAYS": "2555",
    "AIOPS_SECRET_PROVIDER": "vault",
    "AIOPS_VAULT_ADDR": "http://vault:8200",
    "AIOPS_VAULT_TOKEN_FILE": "/run/vault/vault-token",
    "AIOPS_VAULT_TOKEN_HOST_FILE": f"{root}/shared/vault/vault-token",
    "AIOPS_VAULT_STATE_DIR": f"{root}/shared/vault/state",
    "AIOPS_VAULT_KV_MOUNT": "kv",
    "AIOPS_OUTBOUND_ALLOWED_HOSTS": "[]",
    "AIOPS_OIDC_ENABLED": "false",
    "AIOPS_OIDC_ISSUER_URL": "",
    "AIOPS_OIDC_CLIENT_ID": "",
    "AIOPS_OIDC_CLIENT_SECRET": "",
    "AIOPS_OIDC_REDIRECT_URI": f"http://{server}:8080/api/v1/auth/oidc/callback",
    "AIOPS_OIDC_SCOPES": "openid profile email",
    "AIOPS_OIDC_AUTO_PROVISION": "false",
    "AIOPS_OIDC_DEFAULT_ROLE_NAMES": "[]",
    "AIOPS_ABAC_ENFORCED": "false",
}
additions = [f"{name}={value}" for name, value in values.items() if name not in names]
target.write_text(
    existing
    + "\n\n# Added by the enterprise environment upgrader.\n"
    + "\n".join(additions)
    + "\n"
)
os.chmod(target, 0o600)
PY
mv "$temporary_file" "$environment_file"
chmod 0600 "$environment_file"
if [[ ! -e "$deployment_root/shared/vault/vault-token" ]]; then
  : >"$deployment_root/shared/vault/vault-token"
fi
chmod 0600 "$deployment_root/shared/vault/vault-token"
chmod 0700 "$deployment_root/shared/vault/state"
deployment_log "shared environment upgraded; existing values were preserved"
deployment_log "private backup: $backup_path"
