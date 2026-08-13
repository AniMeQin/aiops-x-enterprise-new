#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

compose_root=
environment_file=
state_directory=
token_file=
apply=false

usage() {
  cat <<'EOF'
Usage: bootstrap-vault.sh --compose-root PATH --env-file PATH --state-dir PATH --token-file PATH [--apply]

Initializes or unseals the Compose Vault, enables KV v2, and issues a scoped API
service token. Recovery material is stored with mode 0600 and is never printed.
Without --apply the command performs validation only.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-root) compose_root=$2; shift 2 ;;
    --env-file) environment_file=$2; shift 2 ;;
    --state-dir) state_directory=$2; shift 2 ;;
    --token-file) token_file=$2; shift 2 ;;
    --apply) apply=true; shift ;;
    --help) usage; exit 0 ;;
    *) usage >&2; deployment_fail "unknown argument: $1" ;;
  esac
done

for value in "$compose_root" "$environment_file" "$state_directory" "$token_file"; do
  [[ -n "$value" ]] || { usage >&2; deployment_fail "all path arguments are required"; }
done
compose_root=$(cd "$compose_root" && pwd)
[[ -f "$compose_root/compose.yaml" ]] || deployment_fail "compose.yaml not found"
[[ -f "$environment_file" ]] || deployment_fail "environment file not found"
command -v docker >/dev/null 2>&1 || deployment_fail "docker is required"
command -v python3 >/dev/null 2>&1 || deployment_fail "python3 is required"
if [[ "$apply" != true ]]; then
  deployment_log "validation passed; --apply would initialize or unseal the Compose Vault"
  exit 0
fi

umask 077
mkdir -p "$state_directory" "$(dirname "$token_file")"
chmod 0700 "$state_directory"
temporary_directory=$(mktemp -d "$state_directory/bootstrap.XXXXXX")
cleanup_temporary_directory() {
  rm -f "$temporary_directory/init.json" \
    "$temporary_directory/api-policy.hcl" \
    "$temporary_directory/service-token.json"
  rmdir "$temporary_directory" 2>/dev/null || true
}
trap cleanup_temporary_directory EXIT
compose=(docker compose --env-file "$environment_file" -f "$compose_root/compose.yaml")

status_json=
for _attempt in $(seq 1 30); do
  status_json=$("${compose[@]}" exec -T vault vault status -format=json 2>/dev/null || true)
  [[ -n "$status_json" ]] && break
  sleep 1
done
[[ -n "$status_json" ]] || deployment_fail "Vault did not become reachable within 30 seconds"
initialized=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("initialized", False)).lower())' <<<"$status_json" 2>/dev/null || printf false)
if [[ "$initialized" != true ]]; then
  "${compose[@]}" exec -T vault vault operator init \
    -key-shares=1 -key-threshold=1 -format=json >"$temporary_directory/init.json"
  python3 - "$temporary_directory/init.json" "$state_directory" <<'PY'
import json
import os
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text())
outputs = {
    "unseal-key": document["unseal_keys_b64"][0],
    "root-token": document["root_token"],
}
root = pathlib.Path(sys.argv[2])
for name, value in outputs.items():
    target = root / name
    temporary = target.with_suffix(".incoming")
    temporary.write_text(value)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
PY
fi

unseal_key_file="$state_directory/unseal-key"
root_token_file="$state_directory/root-token"
[[ -s "$unseal_key_file" && -s "$root_token_file" ]] || \
  deployment_fail "Vault is initialized but local recovery material is unavailable"
unseal_key=$(<"$unseal_key_file")
root_token=$(<"$root_token_file")
"${compose[@]}" exec -T vault vault operator unseal "$unseal_key" >/dev/null

if ! "${compose[@]}" exec -T -e VAULT_TOKEN="$root_token" vault \
  vault secrets list -format=json | python3 -c 'import json,sys; raise SystemExit(0 if "kv/" in json.load(sys.stdin) else 1)'; then
  "${compose[@]}" exec -T -e VAULT_TOKEN="$root_token" vault \
    vault secrets enable -path=kv kv-v2 >/dev/null
fi
cat >"$temporary_directory/api-policy.hcl" <<'EOF'
path "kv/data/aiops-x/*" { capabilities = ["read"] }
path "kv/metadata/aiops-x/*" { capabilities = ["read", "list"] }
EOF
"${compose[@]}" exec -T -e VAULT_TOKEN="$root_token" vault \
  vault policy write aiops-x-api - <"$temporary_directory/api-policy.hcl" >/dev/null
existing_service_token=
if [[ -s "$token_file" ]]; then
  existing_service_token=$(<"$token_file")
fi
if [[ -n "$existing_service_token" ]] && \
  "${compose[@]}" exec -T -e VAULT_TOKEN="$existing_service_token" vault \
    vault token lookup >/dev/null 2>&1; then
  "${compose[@]}" exec -T -e VAULT_TOKEN="$existing_service_token" vault \
    vault token renew >/dev/null
  chmod 0600 "$token_file"
else
  "${compose[@]}" exec -T -e VAULT_TOKEN="$root_token" vault \
    vault token create -orphan -policy=aiops-x-api -period=720h -format=json \
    >"$temporary_directory/service-token.json"
  python3 - "$temporary_directory/service-token.json" "$token_file" <<'PY'
import json
import os
import pathlib
import sys

token = json.loads(pathlib.Path(sys.argv[1]).read_text())["auth"]["client_token"]
target = pathlib.Path(sys.argv[2])
temporary = target.with_suffix(".incoming")
temporary.write_text(token)
os.chmod(temporary, 0o600)
os.replace(temporary, target)
PY
fi
deployment_log "Vault is initialized, unsealed, and the scoped API token file was refreshed"
deployment_log "recovery material remains under the protected state directory"
