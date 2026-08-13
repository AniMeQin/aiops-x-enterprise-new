#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

archive_path=
checksum_path=
release_id=
agent_server_name=
deployment_root=/home/qyy/aiops-x
apply=false
switched=false
deployment_complete=false
migration_completed=false
expected_alembic_head=0014_security_center
previous_release=
release_directory=

usage() {
  cat <<'EOF'
Usage: install-release.sh --archive PATH --checksum-file PATH --release-id ID \
  --agent-server-name IP_OR_DNS [options]

Options:
  --root PATH              Persistent deployment root.
  --apply                  Execute the deployment. Without this flag, only
                           artifact integrity and the deployment plan are checked.
  --help                   Show this help.

Safety properties:
  - existing releases, shared configuration, named volumes, and backups are kept;
  - the archive SHA-256 is checked before extraction;
  - the current PostgreSQL database is dumped and verified before migration;
  - the current symlink changes atomically only after migration succeeds;
  - a failed service start restores the previous code pointer and services;
  - database migrations are never automatically downgraded.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive)
      archive_path=$2
      shift 2
      ;;
    --checksum-file)
      checksum_path=$2
      shift 2
      ;;
    --release-id)
      release_id=$2
      shift 2
      ;;
    --agent-server-name)
      agent_server_name=$2
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

if [[ -z "$archive_path" || -z "$checksum_path" || -z "$release_id" || -z "$agent_server_name" ]]; then
  usage >&2
  deployment_fail "archive, checksum file, release ID, and Agent server name are required"
fi
validate_deployment_root "$deployment_root"
validate_release_id "$release_id"
case "$agent_server_name" in
  *:* | */* | '' ) deployment_fail "invalid Agent server IP or DNS name" ;;
esac

if [[ ! -f "$archive_path" || ! -f "$checksum_path" ]]; then
  deployment_fail "archive or checksum file does not exist"
fi
archive_path=$(cd "$(dirname "$archive_path")" && pwd)/$(basename "$archive_path")
checksum_path=$(cd "$(dirname "$checksum_path")" && pwd)/$(basename "$checksum_path")
expected_archive_name="aiops-x-enterprise-$release_id.tar.gz"
if [[ "$(basename "$archive_path")" != "$expected_archive_name" ]]; then
  deployment_fail "archive filename does not match release ID: expected $expected_archive_name"
fi
if [[ "$(basename "$checksum_path")" != "$expected_archive_name.sha256" ]]; then
  deployment_fail "checksum filename does not match release ID"
fi

expected_sha=$(awk 'NR == 1 {print $1}' "$checksum_path")
checksum_archive_name=$(awk 'NR == 1 {print $2}' "$checksum_path")
checksum_archive_name=${checksum_archive_name#\*}
if [[ ! "$expected_sha" =~ ^[0-9a-fA-F]{64}$ ]]; then
  deployment_fail "checksum file does not begin with a valid SHA-256"
fi
if [[ "$checksum_archive_name" != "$expected_archive_name" ]]; then
  deployment_fail "checksum file references an unexpected archive name"
fi
actual_sha=$(calculate_sha256 "$archive_path")
actual_sha_normalized=$(printf '%s' "$actual_sha" | tr 'A-F' 'a-f')
expected_sha_normalized=$(printf '%s' "$expected_sha" | tr 'A-F' 'a-f')
if [[ "$actual_sha_normalized" != "$expected_sha_normalized" ]]; then
  deployment_fail "release archive SHA-256 mismatch"
fi
deployment_log "release archive SHA-256 verified: $actual_sha"

archive_listing=$(tar -tzf "$archive_path")
if grep -Eq '(^/|(^|/)\.\.(/|$))' <<<"$archive_listing"; then
  deployment_fail "archive contains an absolute or parent-traversal path"
fi
top_level_count=$(awk -F/ 'NF && !seen[$1]++ {count++} END {print count + 0}' \
  <<<"$archive_listing")
if [[ "$top_level_count" != 1 ]]; then
  deployment_fail "archive must contain exactly one top-level directory"
fi

deployment_log "deployment root: $deployment_root"
deployment_log "release ID: $release_id"
deployment_log "Agent TLS name: $agent_server_name"
if [[ "$apply" != true ]]; then
  deployment_log "dry run complete; rerun with --apply only after remote preflight passes"
  exit 0
fi

for required_command in curl docker openssl python3 tar; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    deployment_fail "required command is unavailable: $required_command"
  fi
done
if ! docker info >/dev/null 2>&1; then
  deployment_fail "Docker daemon is not reachable"
fi

umask 077
mkdir -p \
  "$deployment_root/releases" \
  "$deployment_root/backups" \
  "$deployment_root/shared"

if [[ ! -f "$deployment_root/shared/.env" ]]; then
  deployment_fail "shared/.env is missing; refusing to initialize credentials implicitly"
fi
environment_mode=$(file_mode "$deployment_root/shared/.env")
if (( (8#$environment_mode & 077) != 0 )); then
  deployment_fail "shared/.env permissions must be 0600 or stricter"
fi
if [[ ! -s "$deployment_root/shared/alertmanager-webhook-token" ]]; then
  deployment_fail \
    "shared Alertmanager token file is missing; run sync-alertmanager-token.sh --apply first"
fi

release_directory="$deployment_root/releases/$release_id"
incoming_directory="$deployment_root/releases/.incoming-$release_id"
if [[ -e "$release_directory" || -e "$incoming_directory" ]]; then
  deployment_fail "release or incoming directory already exists for $release_id"
fi
mkdir "$incoming_directory"
# The installer deliberately uses umask 077 for runtime evidence and secrets.
# Preserve the audited release archive modes so bind-mounted static service
# configuration remains readable by the non-root UIDs used by Prometheus,
# Alertmanager, Loki, Tempo, Grafana, and the OTel collector.
tar -xzpf "$archive_path" -C "$incoming_directory"
top_level_name=$(awk -F/ 'NF && !printed {print $1; printed=1}' <<<"$archive_listing")
if [[ ! -f "$incoming_directory/$top_level_name/compose.yaml" ]]; then
  deployment_fail "extracted release is missing compose.yaml"
fi
mv "$incoming_directory/$top_level_name" "$release_directory"
rmdir "$incoming_directory"

pki_directory="$deployment_root/shared/pki"
required_pki_files='agent-ca-key.pem agent-ca-cert.pem agent-server-key.pem agent-server-cert.pem agent-task-signing-key.pem agent-task-signing-cert.pem'
pki_file_count=0
for pki_file in $required_pki_files; do
  if [[ -s "$pki_directory/$pki_file" ]]; then
    pki_file_count=$((pki_file_count + 1))
  fi
done
if [[ $pki_file_count -eq 0 ]]; then
  if [[ -d "$pki_directory" ]] && find "$pki_directory" -mindepth 1 -print -quit | grep -q .; then
    deployment_fail "shared PKI directory contains unknown files; refusing automatic generation"
  fi
  deployment_log "generating first Agent PKI in shared storage"
  "$release_directory/scripts/generate-agent-pki.sh" "$pki_directory" "$agent_server_name"
elif [[ $pki_file_count -ne 6 ]]; then
  deployment_fail "shared Agent PKI is partial; refusing to overwrite it"
else
  deployment_log "preserving existing shared Agent PKI"
fi

previous_release=$(resolve_current_release "$deployment_root")
backup_directory="$deployment_root/backups/$release_id"
if [[ -e "$backup_directory" ]]; then
  deployment_fail "backup directory already exists for $release_id"
fi
mkdir "$backup_directory"
printf '%s\n' "${previous_release:-none}" >"$backup_directory/previous-release.txt"
printf '%s\n' "$actual_sha" >"$backup_directory/release.sha256"

"$release_directory/scripts/deployment/upgrade-shared-environment.sh" \
  --root "$deployment_root" --apply

previous_release_supports_current_schema() {
  local previous_schema_output
  previous_schema_output=$(run_release_compose \
    "$previous_release" "$deployment_root" run --rm api alembic current 2>/dev/null) || return 1
  grep -q "$expected_alembic_head" <<<"$previous_schema_output"
}

start_release_services() {
  local release_directory=$1
  run_release_compose "$release_directory" "$deployment_root" up -d --build --wait
  # Nginx resolves the API container address when it starts. Recreate both
  # gateways after the API switch even when their own image/config is unchanged.
  run_release_compose "$release_directory" "$deployment_root" \
    up -d --no-deps --force-recreate --wait web agent-gateway
}

rollback_after_error() {
  local exit_code=$?
  set +e
  deployment_log "deployment failed with exit code $exit_code"
  if [[ "$switched" == true && "$deployment_complete" != true ]]; then
    if [[ -n "$previous_release" ]]; then
      previous_id=$(basename "$previous_release")
      if [[ "$migration_completed" != true ]] || previous_release_supports_current_schema; then
        deployment_log "restoring schema-compatible previous code pointer: $previous_id"
        atomic_release_link "$deployment_root" "$previous_id"
        start_release_services "$previous_release"
      else
        deployment_log \
          "previous release is incompatible with the migrated schema; preserving the new code pointer"
        deployment_log "attempting forward recovery of release $release_id"
        if ! start_release_services "$release_directory"; then
          deployment_log \
            "forward recovery did not restore health; keep current on $release_id and inspect evidence"
        fi
      fi
    elif [[ -L "$deployment_root/current" ]]; then
      failed_link="$deployment_root/failed-current-$release_id"
      if [[ ! -e "$failed_link" && ! -L "$failed_link" ]]; then
        mv "$deployment_root/current" "$failed_link"
      fi
    fi
  fi
  deployment_log "database schema was not downgraded; inspect $backup_directory before further action"
  exit "$exit_code"
}
trap rollback_after_error ERR

if [[ -n "$previous_release" ]]; then
  deployment_log "capturing current service state"
  run_release_compose "$previous_release" "$deployment_root" ps \
    >"$backup_directory/compose-ps-before.txt"
  run_release_compose "$previous_release" "$deployment_root" config --images \
    >"$backup_directory/images-before.txt"
  if ! run_release_compose "$previous_release" "$deployment_root" ps \
      --status running --services | grep -qx postgres; then
    deployment_fail "existing PostgreSQL service is not running; cannot create a safe backup"
  fi
  deployment_log "creating PostgreSQL custom-format backup"
  run_release_compose "$previous_release" "$deployment_root" exec -T postgres \
    sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    >"$backup_directory/postgres-before.dump"
  if [[ ! -s "$backup_directory/postgres-before.dump" ]]; then
    deployment_fail "PostgreSQL backup is empty"
  fi
  run_release_compose "$previous_release" "$deployment_root" exec -T postgres \
    pg_restore --list <"$backup_directory/postgres-before.dump" >/dev/null
  deployment_log "PostgreSQL backup verified"
else
  deployment_log "no current release; treating this as first install"
fi

"$release_directory/scripts/deployment/remote-preflight.sh" \
  --root "$deployment_root" \
  --release-dir "$release_directory" \
  --agent-server-name "$agent_server_name"

deployment_log "building release images without switching current"
run_release_compose "$release_directory" "$deployment_root" build
if [[ -z "$previous_release" ]]; then
  deployment_log "starting first-install data services"
  run_release_compose "$release_directory" "$deployment_root" \
    up -d --wait postgres redis nats minio
else
  deployment_log "preserving the running data services until the release switch"
fi

deployment_log "starting and initializing the Vault secret provider"
run_release_compose "$release_directory" "$deployment_root" up -d vault
if [[ "${AIOPS_DEPLOYMENT_TEST_MODE:-0}" != 1 ]]; then
  "$release_directory/scripts/deployment/bootstrap-vault.sh" \
    --compose-root "$release_directory" \
    --env-file "$deployment_root/shared/.env" \
    --state-dir "$deployment_root/shared/vault/state" \
    --token-file "$deployment_root/shared/vault/vault-token" \
    --apply
else
  deployment_log "deployment test mode: Vault bootstrap execution skipped"
fi

deployment_log "applying Alembic migrations"
run_release_compose "$release_directory" "$deployment_root" run --rm api \
  alembic upgrade head
run_release_compose "$release_directory" "$deployment_root" run --rm api \
  alembic current >"$backup_directory/alembic-current-after.txt"
if ! grep -q "$expected_alembic_head" "$backup_directory/alembic-current-after.txt"; then
  deployment_fail "database did not reach $expected_alembic_head"
fi
migration_completed=true

deployment_log "atomically switching current release"
atomic_release_link "$deployment_root" "$release_id"
switched=true

deployment_log "starting all default services and waiting for health"
start_release_services "$release_directory"

deployment_log "running local service smoke checks"
curl -fsS http://127.0.0.1:8000/ready | grep -q '"status":"ok"'
web_bind=$(environment_value "$deployment_root/shared/.env" AIOPS_WEB_BIND)
agent_bind=$(environment_value "$deployment_root/shared/.env" AIOPS_AGENT_BIND)
curl -fsS "http://$web_bind:8080/" >/dev/null
web_api_status=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' "http://$web_bind:8080/api/v1/auth/login")
if [[ "$web_api_status" != 405 ]]; then
  deployment_fail "Web API proxy probe returned HTTP $web_api_status instead of 405"
fi
agent_gateway_status=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' \
  --cacert "$pki_directory/agent-ca-cert.pem" \
  --resolve "$agent_server_name:8443:$agent_bind" \
  "https://$agent_server_name:8443/api/v1/agents/enroll")
if [[ "$agent_gateway_status" != 405 ]]; then
  deployment_fail "Agent gateway enrollment probe returned HTTP $agent_gateway_status instead of 405"
fi

run_release_compose "$release_directory" "$deployment_root" ps \
  >"$backup_directory/compose-ps-after.txt"
run_release_compose "$release_directory" "$deployment_root" config --images \
  >"$backup_directory/images-after.txt"
cat >"$backup_directory/deployment-evidence.txt" <<EOF
release_id=$release_id
archive_sha256=$actual_sha
previous_release=${previous_release:-none}
alembic_head=$expected_alembic_head
web_smoke=passed
web_api_proxy_smoke=passed
api_ready=passed
agent_gateway_smoke=passed
completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF
chmod -R a-w "$release_directory"
deployment_complete=true
trap - ERR
deployment_log "release $release_id installed successfully"
deployment_log "evidence directory: $backup_directory"
