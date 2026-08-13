#!/bin/sh

set -eu
umask 077

mc alias set local "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing "local/$AIOPS_REPORT_BUCKET" >/dev/null
mc mb --ignore-existing --with-lock "local/$AIOPS_AUDIT_ARCHIVE_BUCKET" >/dev/null
mc version enable "local/$AIOPS_REPORT_BUCKET" >/dev/null
mc version enable "local/$AIOPS_AUDIT_ARCHIVE_BUCKET" >/dev/null
mc retention set --default GOVERNANCE "${AIOPS_AUDIT_RETENTION_DAYS}d" \
  "local/$AIOPS_AUDIT_ARCHIVE_BUCKET" >/dev/null

cat >/tmp/api-policy.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::$AIOPS_REPORT_BUCKET"]},
  {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject"],"Resource":["arn:aws:s3:::$AIOPS_REPORT_BUCKET/*"]}
]}
EOF
cat >/tmp/worker-policy.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["s3:GetBucketLocation","s3:ListBucket"],"Resource":["arn:aws:s3:::$AIOPS_AUDIT_ARCHIVE_BUCKET"]},
  {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:GetObjectRetention","s3:PutObjectRetention"],"Resource":["arn:aws:s3:::$AIOPS_AUDIT_ARCHIVE_BUCKET/*"]}
]}
EOF
mc admin policy create local aiops-x-api-reports /tmp/api-policy.json >/dev/null
mc admin policy create local aiops-x-worker-audit /tmp/worker-policy.json >/dev/null
mc admin user info local "$MINIO_API_USER" >/dev/null 2>&1 || \
  mc admin user add local "$MINIO_API_USER" "$MINIO_API_PASSWORD" >/dev/null
mc admin user info local "$MINIO_WORKER_USER" >/dev/null 2>&1 || \
  mc admin user add local "$MINIO_WORKER_USER" "$MINIO_WORKER_PASSWORD" >/dev/null
# Earlier releases attached the built-in readwrite policy. Detach it during the
# idempotent upgrade before applying the bucket-scoped identities.
mc admin policy detach local readwrite --user "$MINIO_API_USER" >/dev/null 2>&1 || true
mc admin policy detach local readwrite --user "$MINIO_WORKER_USER" >/dev/null 2>&1 || true
# MinIO returns a non-zero "no net effect" response when an already-attached
# policy is applied again. The target policy documents were recreated above, so
# an existing attachment is the desired idempotent state.
mc admin policy attach local aiops-x-api-reports --user "$MINIO_API_USER" >/dev/null 2>&1 || true
mc admin policy attach local aiops-x-worker-audit --user "$MINIO_WORKER_USER" >/dev/null 2>&1 || true
