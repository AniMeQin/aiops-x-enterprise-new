#!/usr/bin/env bash

set -Eeuo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
release_id=20990101T000000Z

assert_contains() {
  local value=$1
  local expected=$2
  if [[ "$value" != *"$expected"* ]]; then
    printf 'assertion failed: expected output to contain %s\n' "$expected" >&2
    return 1
  fi
}

temporary_root=$(mktemp -d)
output_directory="$temporary_root/artifacts"

"$repository_root/scripts/release/create-release-archive.sh" \
  --source "$repository_root" \
  --output-dir "$output_directory" \
  --release-id "$release_id"

archive_path="$output_directory/aiops-x-enterprise-$release_id.tar.gz"
checksum_path="$archive_path.sha256"
[[ -s "$archive_path" ]]
[[ -s "$checksum_path" ]]

expected_sha=$(awk 'NR == 1 {print $1}' "$checksum_path")
actual_sha=$(shasum -a 256 "$archive_path" | awk '{print $1}')
[[ "$expected_sha" == "$actual_sha" ]]

archive_listing=$(tar -tzf "$archive_path")
assert_contains "$archive_listing" '/.env.example'
assert_contains "$archive_listing" '/scripts/deployment/install-release.sh'
assert_contains "$archive_listing" '/scripts/acceptance/m1_live.py'
assert_contains "$archive_listing" '/scripts/acceptance/m1_persistence.py'
assert_contains "$archive_listing" '/scripts/acceptance/m2_live.py'
assert_contains "$archive_listing" '/scripts/acceptance/m2_supplemental_live.py'
assert_contains "$archive_listing" '/scripts/acceptance/enterprise_live.py'
assert_contains "$archive_listing" '/scripts/acceptance/first_e2e_live.py'
assert_contains "$archive_listing" '/scripts/backup/backup-production.sh'
assert_contains "$archive_listing" '/scripts/backup/restore-production.sh'
assert_contains "$archive_listing" '/scripts/backup/dr-exercise.sh'
assert_contains "$archive_listing" '/migrations/versions/0008_agent_certificate_renewal.py'
assert_contains "$archive_listing" '/migrations/versions/0014_security_center.py'
grep -q -- '--schedule=/tmp/celerybeat-schedule' "$repository_root/compose.yaml"
grep -q -- '--force-recreate --wait web agent-gateway' \
  "$repository_root/scripts/deployment/install-release.sh"
grep -q 'web_api_proxy_smoke=passed' \
  "$repository_root/scripts/deployment/install-release.sh"
grep -q 'bootstrap-vault.sh' "$repository_root/scripts/deployment/install-release.sh"
grep -q 'VAULT_ADDR: http://127.0.0.1:8200' "$repository_root/compose.yaml"
grep -q 'aiops-x-api-reports.*MINIO_API_USER.*|| true' \
  "$repository_root/deploy/compose/minio-init.sh"
grep -q 'alertmanager-init:' "$repository_root/compose.yaml"
grep -q 'alertmanager-secrets:/run/secrets:ro' "$repository_root/compose.yaml"
grep -q 'chmod 0400 /target/alertmanager-webhook-token' "$repository_root/compose.yaml"
if printf '%s\n' "$archive_listing" | grep -Eq \
  '(^|/)(\.env|\.venv|node_modules|deploy/pki|__pycache__)(/|$)|-key\.pem$|\.key$'; then
  printf 'archive contains a forbidden path\n' >&2
  exit 1
fi
python3 - "$archive_path" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    names = [name for name in archive.getnames() if name]
    members = {member.name: member for member in archive.getmembers()}

roots = {name.split("/", 1)[0] for name in names}
assert len(roots) == 1, roots
assert not [
    name for name in names if any(part.startswith("._") for part in name.split("/"))
]
root = next(iter(roots))
for relative in (
    "scripts/deployment/bootstrap-vault.sh",
    "scripts/backup/backup-production.sh",
    "scripts/backup/restore-production.sh",
    "scripts/backup/dr-exercise.sh",
    "scripts/supply-chain/verify-image.sh",
    "scripts/acceptance/m1_live.py",
    "scripts/acceptance/m1_persistence.py",
    "scripts/acceptance/m2_live.py",
    "scripts/acceptance/m2_supplemental_live.py",
    "scripts/acceptance/enterprise_live.py",
    "scripts/acceptance/first_e2e_live.py",
):
    assert members[f"{root}/{relative}"].mode & 0o111, relative
PY

dry_run_output=$("$repository_root/scripts/deployment/install-release.sh" \
  --archive "$archive_path" \
  --checksum-file "$checksum_path" \
  --release-id "$release_id" \
  --agent-server-name 192.0.2.96 \
  --root /home/tester/aiops-x)
assert_contains "$dry_run_output" 'release archive SHA-256 verified'
assert_contains "$dry_run_output" 'dry run complete'

if rg -n 'tar -tzf .*\|.*(grep|awk)' \
    "$repository_root/scripts/deployment/install-release.sh" >/dev/null; then
  printf 'installer contains a tar listing pipeline vulnerable to SIGPIPE under pipefail\n' >&2
  exit 1
fi

tampered_archive="$output_directory/tampered.tar.gz"
cp "$archive_path" "$tampered_archive"
printf 'tampered' >>"$tampered_archive"
if "$repository_root/scripts/deployment/install-release.sh" \
    --archive "$tampered_archive" \
    --checksum-file "$checksum_path" \
    --release-id 20990101T000001Z \
    --agent-server-name 192.0.2.96 \
    --root /home/tester/aiops-x >/dev/null 2>&1; then
  printf 'tampered archive was accepted\n' >&2
  exit 1
fi

if "$repository_root/scripts/deployment/install-release.sh" \
    --archive "$archive_path" \
    --checksum-file "$checksum_path" \
    --release-id "$release_id" \
    --agent-server-name 192.0.2.96 \
    --root /tmp/unsafe-root >/dev/null 2>&1; then
  printf 'unsafe deployment root was accepted\n' >&2
  exit 1
fi

printf 'release_script_tests=passed\n'
printf 'temporary_test_root=%s\n' "$temporary_root"
