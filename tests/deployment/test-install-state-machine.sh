#!/usr/bin/env bash

set -Eeuo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
old_release_id=20981231T235959Z
success_release_id=20990102T000000Z
failure_release_id=20990103T000000Z
server_address=192.0.2.96
test_parent="/tmp/aiops-x-deployment-test-${PPID}-${RANDOM}"
fake_bin="$test_parent/fake-bin"
artifact_directory="$test_parent/artifacts"
fake_docker_log="$test_parent/fake-docker.log"
fake_failure_marker="$test_parent/fake-new-up-failed"

mkdir -p "$fake_bin" "$artifact_directory"

cat >"$fake_bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\n' "$*" >>"$FAKE_DOCKER_LOG"

if [[ "${1:-}" == info ]]; then
  exit 0
fi
if [[ "${1:-}" != compose ]]; then
  exit 2
fi
shift

project_directory=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-directory)
      project_directory=$2
      shift 2
      ;;
    -f | --env-file)
      shift 2
      ;;
    *) break ;;
  esac
done

command_name=${1:-}
shift || true
case "$command_name" in
  version)
    printf 'Docker Compose version v2.test\n'
    ;;
  config)
    if [[ " $* " == *' --services '* ]]; then
      printf '%s\n' postgres redis nats minio api worker ai-engine web agent-gateway \
        node-exporter prometheus alertmanager loki tempo otel-collector grafana
    elif [[ " $* " == *' --images '* ]]; then
      printf 'aiops-x-test-image\n'
    fi
    ;;
  ps)
    if [[ " $* " == *' --status running --services '* ]]; then
      printf 'postgres\n'
    else
      printf 'NAME STATUS\naiops-x-test healthy\n'
    fi
    ;;
  exec)
    if [[ " $* " == *'pg_dump'* ]]; then
      printf 'FAKE_CUSTOM_FORMAT_POSTGRES_BACKUP\n'
    elif [[ " $* " == *'pg_restore --list'* ]]; then
      while IFS= read -r _; do :; done
    fi
    ;;
  run)
    if [[ " $* " == *'alembic current'* ]]; then
      if [[ "${FAKE_OLD_SCHEMA_INCOMPATIBLE:-0}" == 1 && \
          "$project_directory" == *"/$FAKE_OLD_RELEASE_ID" ]]; then
        exit 3
      fi
      printf '0014_security_center (head)\n'
    fi
    ;;
  build)
    ;;
  up)
    if [[ "${FAKE_DOCKER_FAIL_NEW_UP:-0}" == 1 && \
        "$project_directory" == *"/$FAKE_NEW_RELEASE_ID" && \
        ! -e "$FAKE_DOCKER_FAILURE_MARKER" ]]; then
      : >"$FAKE_DOCKER_FAILURE_MARKER"
      exit 42
    fi
    ;;
  *)
    printf 'unsupported fake docker compose command: %s\n' "$command_name" >&2
    exit 2
    ;;
esac
DOCKER

cat >"$fake_bin/curl" <<'CURL'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ " $* " == *"%{http_code}"* ]]; then
  printf '405'
elif [[ " $* " == *'/ready '* || " $* " == *'/ready' ]]; then
  printf '{"status":"ok"}\n'
else
  printf '<!doctype html><title>AIOps-X Test</title>\n'
fi
CURL
chmod +x "$fake_bin/docker" "$fake_bin/curl"

export PATH="$fake_bin:$PATH"
export AIOPS_DEPLOYMENT_TEST_MODE=1
export FAKE_DOCKER_LOG="$fake_docker_log"
export FAKE_DOCKER_FAILURE_MARKER="$fake_failure_marker"
export FAKE_OLD_RELEASE_ID="$old_release_id"

"$repository_root/scripts/release/create-release-archive.sh" \
  --source "$repository_root" \
  --output-dir "$artifact_directory" \
  --release-id "$success_release_id"
archive_path="$artifact_directory/aiops-x-enterprise-$success_release_id.tar.gz"
checksum_path="$archive_path.sha256"
"$repository_root/scripts/release/create-release-archive.sh" \
  --source "$repository_root" \
  --output-dir "$artifact_directory" \
  --release-id "$failure_release_id"
failure_archive_path="$artifact_directory/aiops-x-enterprise-$failure_release_id.tar.gz"
failure_checksum_path="$failure_archive_path.sha256"

prepare_deployment_root() {
  local deployment_root=$1
  export AIOPS_DEPLOYMENT_TEST_ROOT=$deployment_root
  "$repository_root/scripts/deployment/initialize-test-environment.sh" \
    --root "$deployment_root" \
    --server-address "$server_address" \
    --apply
  mkdir -p "$deployment_root/releases/$old_release_id"
  cp "$repository_root/compose.yaml" "$deployment_root/releases/$old_release_id/compose.yaml"
  ln -s "releases/$old_release_id" "$deployment_root/current"
}

success_root="$test_parent/success-root"
prepare_deployment_root "$success_root"
export FAKE_NEW_RELEASE_ID=$success_release_id
"$repository_root/scripts/deployment/install-release.sh" \
  --archive "$archive_path" \
  --checksum-file "$checksum_path" \
  --release-id "$success_release_id" \
  --agent-server-name "$server_address" \
  --root "$success_root" \
  --apply

[[ "$(readlink "$success_root/current")" == "releases/$success_release_id" ]]
[[ -s "$success_root/backups/$success_release_id/postgres-before.dump" ]]
[[ -s "$success_root/backups/$success_release_id/deployment-evidence.txt" ]]
grep -q '^alembic_head=0014_security_center$' \
  "$success_root/backups/$success_release_id/deployment-evidence.txt"
grep -q 'alembic upgrade head' "$fake_docker_log"
grep -q -- "--project-directory $success_root/releases/$success_release_id" "$fake_docker_log"
grep -q -- 'up -d --no-deps --force-recreate --wait web agent-gateway' "$fake_docker_log"
python3 - "$success_root/releases/$success_release_id/deploy/monitoring/alertmanager.yml" <<'PY'
import os
import stat
import sys

mode = stat.S_IMODE(os.stat(sys.argv[1]).st_mode)
assert mode & 0o044 == 0o044, oct(mode)
PY

rollback_dry_run=$("$repository_root/scripts/deployment/rollback-release.sh" \
  --root "$success_root" \
  --target-release-id "$old_release_id")
[[ "$rollback_dry_run" == *'dry run complete'* ]]
"$repository_root/scripts/deployment/rollback-release.sh" \
  --root "$success_root" \
  --target-release-id "$old_release_id" \
  --apply
[[ "$(readlink "$success_root/current")" == "releases/$old_release_id" ]]
rollback_evidence=$(find "$success_root/backups" -mindepth 2 -maxdepth 2 \
  -name rollback-evidence.txt -print -quit)
[[ -s "$rollback_evidence" ]]
grep -q '^database_restore=not_performed$' "$rollback_evidence"

failure_root="$test_parent/failure-root"
prepare_deployment_root "$failure_root"
export FAKE_NEW_RELEASE_ID=$failure_release_id
export FAKE_DOCKER_FAIL_NEW_UP=1
if "$repository_root/scripts/deployment/install-release.sh" \
    --archive "$failure_archive_path" \
    --checksum-file "$failure_checksum_path" \
    --release-id "$failure_release_id" \
    --agent-server-name "$server_address" \
    --root "$failure_root" \
    --apply; then
  printf 'simulated new release start failure was not propagated\n' >&2
  exit 1
fi
unset FAKE_DOCKER_FAIL_NEW_UP

[[ "$(readlink "$failure_root/current")" == "releases/$old_release_id" ]]
[[ -s "$failure_root/backups/$failure_release_id/postgres-before.dump" ]]
[[ ! -e "$failure_root/backups/$failure_release_id/deployment-evidence.txt" ]]
[[ -e "$fake_failure_marker" ]]

forward_root="$test_parent/forward-root"
rm -f "$fake_failure_marker"
prepare_deployment_root "$forward_root"
export FAKE_DOCKER_FAIL_NEW_UP=1
export FAKE_OLD_SCHEMA_INCOMPATIBLE=1
if "$repository_root/scripts/deployment/install-release.sh" \
    --archive "$failure_archive_path" \
    --checksum-file "$failure_checksum_path" \
    --release-id "$failure_release_id" \
    --agent-server-name "$server_address" \
    --root "$forward_root" \
    --apply; then
  printf 'simulated forward-recovery deployment failure was not propagated\n' >&2
  exit 1
fi
unset FAKE_DOCKER_FAIL_NEW_UP FAKE_OLD_SCHEMA_INCOMPATIBLE

[[ "$(readlink "$forward_root/current")" == "releases/$failure_release_id" ]]
[[ -s "$forward_root/backups/$failure_release_id/postgres-before.dump" ]]
grep -q -- "forward-root/releases/$old_release_id" "$fake_docker_log"
grep -q -- "forward-root/releases/$failure_release_id" "$fake_docker_log"

printf 'install_state_machine_tests=passed\n'
printf 'temporary_test_root=%s\n' "$test_parent"
