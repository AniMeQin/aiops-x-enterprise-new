#!/usr/bin/env bash

set -Eeuo pipefail

output_root=
database_service=${AIOPS_BACKUP_PG_SERVICE:-}
object_alias=${AIOPS_BACKUP_MC_ALIAS:-}
object_bucket=${AIOPS_BACKUP_BUCKET:-}

usage() {
  cat <<'EOF'
Usage: backup-production.sh --output-root PATH [--database-service PGSERVICE]

Requires a protected PGSERVICEFILE and PGSERVICE; credentials are never placed
on the command line. If AIOPS_BACKUP_MC_ALIAS and AIOPS_BACKUP_BUCKET are set,
the verified bundle is copied to that preconfigured object-store alias.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root) output_root=$2; shift 2 ;;
    --database-service) database_service=$2; shift 2 ;;
    --help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n "$output_root" && -n "$database_service" ]] || { usage >&2; exit 2; }
[[ -n "${PGSERVICEFILE:-}" && -f "$PGSERVICEFILE" ]] || {
  echo "PGSERVICEFILE must reference a protected PostgreSQL service file" >&2; exit 2;
}
mode=$(stat -f '%Lp' "$PGSERVICEFILE" 2>/dev/null || stat -c '%a' "$PGSERVICEFILE")
(( (8#$mode & 077) == 0 )) || { echo "PGSERVICEFILE permissions must be 0600" >&2; exit 2; }
for command in pg_dump pg_restore sha256sum; do
  command -v "$command" >/dev/null 2>&1 || { echo "$command is required" >&2; exit 2; }
done

umask 077
timestamp=$(date -u '+%Y%m%dT%H%M%SZ')
backup_directory="$output_root/$timestamp"
[[ ! -e "$backup_directory" ]] || { echo "backup already exists: $backup_directory" >&2; exit 1; }
mkdir -p "$backup_directory"
pg_dump --dbname="service=$database_service" --format=custom \
  --file="$backup_directory/postgresql.dump"
pg_restore --list "$backup_directory/postgresql.dump" \
  >"$backup_directory/postgresql.contents"
pg_dump --dbname="service=$database_service" --schema-only --no-owner --no-privileges \
  --file="$backup_directory/schema.sql"
(
  cd "$backup_directory"
  sha256sum postgresql.dump postgresql.contents schema.sql >SHA256SUMS
)
cat >"$backup_directory/manifest.json" <<EOF
{"schema":"aiops-x.backup.v1","created_at":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')","database_service":"$database_service","contents":["postgresql.dump","postgresql.contents","schema.sql","SHA256SUMS"]}
EOF
chmod 0400 "$backup_directory"/*

if [[ -n "$object_alias" || -n "$object_bucket" ]]; then
  [[ -n "$object_alias" && -n "$object_bucket" ]] || {
    echo "both AIOPS_BACKUP_MC_ALIAS and AIOPS_BACKUP_BUCKET are required" >&2; exit 2;
  }
  command -v mc >/dev/null 2>&1 || { echo "mc is required for object upload" >&2; exit 2; }
  mc cp --recursive "$backup_directory" "$object_alias/$object_bucket/postgresql/" >/dev/null
fi
printf 'verified backup created: %s\n' "$backup_directory"
