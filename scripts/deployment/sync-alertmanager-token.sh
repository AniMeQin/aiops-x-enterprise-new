#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

deployment_root=/home/qyy/aiops-x
apply=false

usage() {
  cat <<'EOF'
Usage: sync-alertmanager-token.sh [--root PATH] [--apply]

Without --apply the command validates that the source variable exists and
prints the destination path. With --apply it writes the token to a mode 0600
file without printing the secret. Existing files are never overwritten.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

validate_deployment_root "$deployment_root"
environment_file="$deployment_root/shared/.env"
destination_file="$deployment_root/shared/alertmanager-webhook-token"
if [[ ! -f "$environment_file" ]]; then
  deployment_fail "missing environment file: $environment_file"
fi

token_line=$(grep -m1 '^AIOPS_ALERTMANAGER_WEBHOOK_TOKEN=' "$environment_file" || true)
token_value=${token_line#*=}
if [[ -z "$token_line" || -z "$token_value" ]]; then
  deployment_fail "AIOPS_ALERTMANAGER_WEBHOOK_TOKEN is missing or empty"
fi
if [[ "$token_value" == \"*\" && "$token_value" == *\" ]]; then
  token_value=${token_value:1:${#token_value}-2}
elif [[ "$token_value" == \'*\' && "$token_value" == *\' ]]; then
  token_value=${token_value:1:${#token_value}-2}
fi
if [[ "$token_value" == change-me* || "$token_value" == changeme* ]]; then
  deployment_fail "Alertmanager webhook token is still a placeholder"
fi

if [[ "$apply" != true ]]; then
  deployment_log "validation passed; --apply would create $destination_file"
  exit 0
fi
if [[ -e "$destination_file" ]]; then
  deployment_fail "destination already exists; refusing to overwrite $destination_file"
fi

umask 077
temporary_file="$destination_file.incoming.$(date -u '+%Y%m%dT%H%M%SZ')"
printf '%s' "$token_value" >"$temporary_file"
chmod 0600 "$temporary_file"
mv "$temporary_file" "$destination_file"
deployment_log "Alertmanager token file created with mode 0600"
