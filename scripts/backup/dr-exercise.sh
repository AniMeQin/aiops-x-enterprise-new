#!/usr/bin/env bash

set -Eeuo pipefail

backup_directory=
target_service=
evidence_file=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-dir) backup_directory=$2; shift 2 ;;
    --target-service) target_service=$2; shift 2 ;;
    --evidence-file) evidence_file=$2; shift 2 ;;
    --help)
      echo "Usage: dr-exercise.sh --backup-dir PATH --target-service NAME --evidence-file PATH"
      exit 0
      ;;
    *) exit 2 ;;
  esac
done
[[ -n "$backup_directory" && -n "$target_service" && -n "$evidence_file" ]] || exit 2
started_epoch=$(date +%s)
"$(dirname "$0")/restore-production.sh" \
  --backup-dir "$backup_directory" \
  --target-service "$target_service" \
  --confirm "$target_service"
tenant_count=$(psql "service=$target_service" -Atqc 'select count(*) from tenants')
audit_count=$(psql "service=$target_service" -Atqc 'select count(*) from audit_logs')
alembic_head=$(psql "service=$target_service" -Atqc 'select version_num from alembic_version')
finished_epoch=$(date +%s)
umask 077
cat >"$evidence_file" <<EOF
exercise=aiops-x-postgresql-isolated-restore
status=passed
target_service=$target_service
alembic_head=$alembic_head
tenant_count=$tenant_count
audit_count=$audit_count
rto_seconds=$((finished_epoch - started_epoch))
completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF
chmod 0400 "$evidence_file"
printf 'DR exercise evidence: %s\n' "$evidence_file"
