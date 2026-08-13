#!/usr/bin/env bash

set -Eeuo pipefail

script_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_directory/../.." && pwd)
# shellcheck source=../deployment/common.sh
source "$repository_root/scripts/deployment/common.sh"

source_directory=$repository_root
output_directory="$repository_root/dist/releases"
release_id=$(date -u '+%Y%m%dT%H%M%SZ')

usage() {
  cat <<'EOF'
Usage: create-release-archive.sh [options]

Options:
  --source PATH       Repository root to package.
  --output-dir PATH   Destination directory (default: dist/releases).
  --release-id ID     UTC release ID in YYYYMMDDTHHMMSSZ format.
  --help              Show this help.

The command never overwrites an existing archive. It excludes credentials,
PKI material, dependencies, caches, reports, and build outputs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      source_directory=$2
      shift 2
      ;;
    --output-dir)
      output_directory=$2
      shift 2
      ;;
    --release-id)
      release_id=$2
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

validate_release_id "$release_id"
source_directory=$(cd "$source_directory" && pwd)
output_directory=$(mkdir -p "$output_directory" && cd "$output_directory" && pwd)
case "$output_directory" in
  "$source_directory"/dist | "$source_directory"/dist/*) ;;
  "$source_directory"/*)
    deployment_fail "an output directory inside the source must be under dist/"
    ;;
esac

for required_file in compose.yaml pyproject.toml package.json Makefile; do
  if [[ ! -f "$source_directory/$required_file" ]]; then
    deployment_fail "source is missing $required_file"
  fi
done

unexpected_environment_file=$(find "$source_directory" -type f -name '.env*' \
  ! -name '.env' ! -name '.env.example' -print -quit)
if [[ -n "$unexpected_environment_file" ]]; then
  deployment_fail \
    "refusing to package while an unexpected environment file exists: $unexpected_environment_file"
fi

archive_path="$output_directory/aiops-x-enterprise-$release_id.tar.gz"
checksum_path="$archive_path.sha256"
if [[ -e "$archive_path" || -e "$checksum_path" ]]; then
  deployment_fail "release artifact already exists for $release_id"
fi

source_parent=$(dirname "$source_directory")
source_name=$(basename "$source_directory")
deployment_log "packaging release $release_id from $source_directory"

# COPYFILE_DISABLE prevents macOS libarchive from emitting hidden AppleDouble
# entries (for example ._AIOps-X-Enterprise-local-recovery) that GNU tar sees as
# a second top-level directory. --no-xattrs keeps the artifact portable as well.
COPYFILE_DISABLE=1 tar --no-xattrs -C "$source_parent" -czf "$archive_path" \
  --exclude="$source_name/.git" \
  --exclude="$source_name/.env" \
  --exclude='*/.env' \
  --exclude="$source_name/.venv" \
  --exclude="$source_name/.venv*" \
  --exclude="$source_name/node_modules" \
  --exclude='*/node_modules' \
  --exclude='*/.venv' \
  --exclude='*/.venv*' \
  --exclude='*/.python-deps*' \
  --exclude="$source_name/dist" \
  --exclude="$source_name/apps/web/dist" \
  --exclude="$source_name/apps/web/playwright-report" \
  --exclude="$source_name/apps/web/test-results" \
  --exclude="$source_name/deploy/pki" \
  --exclude="$source_name/deploy/vault/state" \
  --exclude='*/deploy/vault/*.token' \
  --exclude="$source_name/agents/edge-agent/edge-agent" \
  --exclude="$source_name/.coverage" \
  --exclude="$source_name/.pytest_cache" \
  --exclude="$source_name/.mypy_cache" \
  --exclude="$source_name/.ruff_cache" \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*/._*' \
  --exclude="$source_name/._*" \
  --exclude='*/.DS_Store' \
  "$source_name"

if ! python3 - "$archive_path" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    names = [name for name in archive.getnames() if name]

roots = {name.split("/", 1)[0] for name in names}
appledouble = [
    name for name in names if any(part.startswith("._") for part in name.split("/"))
]
if len(roots) != 1 or appledouble:
    raise SystemExit(1)
PY
then
  deployment_fail "release archive contains AppleDouble metadata or multiple top-level paths"
fi

archive_listing=$(tar -tzf "$archive_path")
if printf '%s\n' "$archive_listing" | grep -Eq \
  '(^|/)(\.env|\.venv|node_modules|deploy/pki|deploy/vault/state|__pycache__)(/|$)|-key\.pem$|\.key$|\.token$'; then
  deployment_fail "release archive contains a forbidden secret or generated path"
fi

archive_sha=$(calculate_sha256 "$archive_path")
printf '%s  %s\n' "$archive_sha" "$(basename "$archive_path")" >"$checksum_path"
chmod 0644 "$archive_path" "$checksum_path"

deployment_log "release archive created: $archive_path"
deployment_log "sha256: $archive_sha"
