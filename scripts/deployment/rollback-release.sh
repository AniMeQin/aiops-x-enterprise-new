#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=common.sh
source "$script_directory/common.sh"

deployment_root=/home/qyy/aiops-x
target_release_id=
apply=false

usage() {
  cat <<'EOF'
Usage: rollback-release.sh --target-release-id ID [options]

Options:
  --root PATH   Persistent deployment root.
  --apply       Execute code rollback. Without this flag, print a dry run.
  --help        Show this help.

This command changes only the current code release and restarts Compose. It
does not restore PostgreSQL or downgrade Alembic. Confirm schema compatibility
before applying it. Existing releases, backups, volumes, and shared config are
preserved.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-release-id)
      target_release_id=$2
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

if [[ -z "$target_release_id" ]]; then
  usage >&2
  deployment_fail "target release ID is required"
fi
validate_deployment_root "$deployment_root"
validate_release_id "$target_release_id"

target_release="$deployment_root/releases/$target_release_id"
if [[ ! -f "$target_release/compose.yaml" ]]; then
  deployment_fail "target release does not exist or is incomplete: $target_release"
fi
current_release=$(resolve_current_release "$deployment_root")
if [[ -z "$current_release" ]]; then
  deployment_fail "there is no current release to roll back"
fi
if [[ "$current_release" == "$target_release" ]]; then
  deployment_fail "target release is already current"
fi
if [[ ! -f "$deployment_root/shared/.env" ]]; then
  deployment_fail "shared environment file is missing"
fi

deployment_log "current release: $(basename "$current_release")"
deployment_log "target release: $target_release_id"
deployment_log "database and named volumes will not be modified or restored"
if [[ "$apply" != true ]]; then
  deployment_log "dry run complete; rerun with --apply after schema compatibility review"
  exit 0
fi

rollback_record="$deployment_root/backups/rollback-$(date -u '+%Y%m%dT%H%M%SZ')"
if [[ -e "$rollback_record" ]]; then
  deployment_fail "rollback evidence directory already exists"
fi
umask 077
mkdir -p "$rollback_record"
printf '%s\n' "$current_release" >"$rollback_record/previous-current.txt"
run_release_compose "$current_release" "$deployment_root" ps \
  >"$rollback_record/compose-ps-before.txt"

start_release_services() {
  local release_directory=$1
  run_release_compose "$release_directory" "$deployment_root" up -d --build --wait
  run_release_compose "$release_directory" "$deployment_root" \
    up -d --no-deps --force-recreate --wait web agent-gateway
}

restore_current_after_error() {
  local exit_code=$?
  set +e
  deployment_log "rollback start failed; restoring original current pointer"
  atomic_release_link "$deployment_root" "$(basename "$current_release")"
  start_release_services "$current_release"
  exit "$exit_code"
}
trap restore_current_after_error ERR

atomic_release_link "$deployment_root" "$target_release_id"
start_release_services "$target_release"
curl -fsS http://127.0.0.1:8000/ready | grep -q '"status":"ok"'
web_bind=$(environment_value "$deployment_root/shared/.env" AIOPS_WEB_BIND)
curl -fsS "http://$web_bind:8080/" >/dev/null
web_api_status=$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' "http://$web_bind:8080/api/v1/auth/login")
if [[ "$web_api_status" != 405 ]]; then
  deployment_fail "Web API proxy probe returned HTTP $web_api_status instead of 405"
fi
run_release_compose "$target_release" "$deployment_root" ps \
  >"$rollback_record/compose-ps-after.txt"
cat >"$rollback_record/rollback-evidence.txt" <<EOF
from_release=$(basename "$current_release")
to_release=$target_release_id
database_restore=not_performed
smoke_checks=passed
web_api_proxy_smoke=passed
completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF
trap - ERR
deployment_log "code rollback to $target_release_id completed"
deployment_log "evidence directory: $rollback_record"
