#!/usr/bin/env bash

set -Eeuo pipefail

backup_directory=
target_service=
confirmation=

usage() {
  cat <<'EOF'
Usage: restore-production.sh --backup-dir PATH --target-service PGSERVICE --confirm PGSERVICE

The target database must already exist, be empty, and use a service name ending
in _restore or _dr. The script never drops or cleans an existing database.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-dir) backup_directory=$2; shift 2 ;;
    --target-service) target_service=$2; shift 2 ;;
    --confirm) confirmation=$2; shift 2 ;;
    --help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ -n "$backup_directory" && -n "$target_service" && "$confirmation" == "$target_service" ]] || {
  usage >&2; exit 2;
}
[[ "$target_service" =~ (_restore|_dr)$ ]] || {
  echo "target service must end in _restore or _dr" >&2; exit 2;
}
[[ -f "$backup_directory/postgresql.dump" && -f "$backup_directory/SHA256SUMS" ]] || {
  echo "backup bundle is incomplete" >&2; exit 2;
}
[[ -n "${PGSERVICEFILE:-}" && -f "$PGSERVICEFILE" ]] || {
  echo "PGSERVICEFILE is required" >&2; exit 2;
}
(
  cd "$backup_directory"
  sha256sum --check SHA256SUMS
)
pg_restore --list "$backup_directory/postgresql.dump" >/dev/null
existing=$(psql "service=$target_service" -Atqc \
  "select count(*) from pg_catalog.pg_tables where schemaname not in ('pg_catalog','information_schema')")
[[ "$existing" == 0 ]] || {
  echo "target database is not empty; refusing restore" >&2; exit 1;
}
pg_restore --dbname="service=$target_service" --no-owner --no-privileges --exit-on-error \
  "$backup_directory/postgresql.dump"
printf 'restore completed into isolated service: %s\n' "$target_service"
