ARG MINIO_MC_IMAGE=minio/mc:RELEASE.2024-06-29T19-08-46Z
ARG POSTGRES_IMAGE=postgres:16.4-bookworm

FROM ${MINIO_MC_IMAGE} AS minio-client
FROM ${POSTGRES_IMAGE}

COPY --from=minio-client /usr/bin/mc /usr/local/bin/mc
COPY scripts/backup/backup-production.sh /usr/local/bin/aiops-x-backup

USER postgres
ENTRYPOINT ["/usr/local/bin/aiops-x-backup"]
