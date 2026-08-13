#!/usr/bin/env bash

set -Eeuo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/bin" "$test_root/output"

cat >"$test_root/bin/pg_dump" <<'EOF'
#!/usr/bin/env bash
set -eu
output=
for argument in "$@"; do
  case "$argument" in --file=*) output=${argument#--file=} ;; esac
done
[[ -n "$output" ]]
printf 'deterministic pg_dump fixture\n' >"$output"
EOF

cat >"$test_root/bin/pg_restore" <<'EOF'
#!/usr/bin/env bash
set -eu
if [[ " $* " == *" --list "* ]]; then
  printf 'verified custom archive contents\n'
fi
EOF

cat >"$test_root/bin/psql" <<'EOF'
#!/usr/bin/env bash
set -eu
case "$*" in
  *pg_catalog.pg_tables*) printf '%s\n' "${FAKE_EXISTING_TABLES:-0}" ;;
  *'count(*) from tenants'*) printf '2\n' ;;
  *'count(*) from audit_logs'*) printf '7\n' ;;
  *'version_num from alembic_version'*) printf '0014_security_center\n' ;;
  *) exit 2 ;;
esac
EOF

chmod 0755 "$test_root/bin/pg_dump" "$test_root/bin/pg_restore" "$test_root/bin/psql"
printf '[aiops_x_backup]\nhost=database.example\n' >"$test_root/pg_service.conf"
chmod 0600 "$test_root/pg_service.conf"

export PATH="$test_root/bin:$PATH"
export PGSERVICEFILE="$test_root/pg_service.conf"
"$repository_root/scripts/backup/backup-production.sh" \
  --output-root "$test_root/output" --database-service aiops_x_backup >/dev/null
backup_directory=$(find "$test_root/output" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$backup_directory" ]]
(cd "$backup_directory" && sha256sum --check SHA256SUMS >/dev/null)
pg_restore --list "$backup_directory/postgresql.dump" >/dev/null

"$repository_root/scripts/backup/restore-production.sh" \
  --backup-dir "$backup_directory" --target-service aiops_x_restore \
  --confirm aiops_x_restore >/dev/null

if FAKE_EXISTING_TABLES=1 "$repository_root/scripts/backup/restore-production.sh" \
  --backup-dir "$backup_directory" --target-service occupied_restore \
  --confirm occupied_restore >/dev/null 2>&1; then
  echo "restore accepted a non-empty target" >&2
  exit 1
fi

if "$repository_root/scripts/backup/restore-production.sh" \
  --backup-dir "$backup_directory" --target-service production \
  --confirm production >/dev/null 2>&1; then
  echo "restore accepted an unsafe target service name" >&2
  exit 1
fi

evidence_file="$test_root/dr-evidence.txt"
"$repository_root/scripts/backup/dr-exercise.sh" \
  --backup-dir "$backup_directory" --target-service quarterly_dr \
  --evidence-file "$evidence_file" >/dev/null
grep -q '^status=passed$' "$evidence_file"
grep -q '^alembic_head=0014_security_center$' "$evidence_file"
grep -q '^tenant_count=2$' "$evidence_file"
grep -q '^audit_count=7$' "$evidence_file"
[[ $(stat -f '%Lp' "$evidence_file" 2>/dev/null || stat -c '%a' "$evidence_file") == 400 ]]

echo 'backup_restore_script_tests=passed'
