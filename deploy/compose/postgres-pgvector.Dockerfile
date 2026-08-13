ARG POSTGRES_IMAGE=postgres:16.4-bookworm
ARG PGVECTOR_BUILDER_IMAGE=gcc:13.3.0-bookworm

FROM ${POSTGRES_IMAGE} AS postgres-base

FROM ${PGVECTOR_BUILDER_IMAGE} AS pgvector-builder
COPY --chmod=0644 deploy/vendor/pgdg-archive-keyring.gpg /etc/apt/keyrings/pgdg-archive-keyring.gpg
COPY deploy/vendor/pgvector-v0.8.0.tar.gz /tmp/pgvector.tar.gz
RUN find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) \
      -exec sed -i \
        -e 's|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
        -e 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g' \
        {} + \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates gpgv \
    && printf '%s\n' \
      'deb [signed-by=/etc/apt/keyrings/pgdg-archive-keyring.gpg] https://mirrors.aliyun.com/postgresql/repos/apt bookworm-pgdg main' \
      > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-server-dev-16 \
    && mkdir /tmp/pgvector /tmp/pgvector-install \
    && echo '867a2c328d4928a5a9d6f052cd3bc78c7d60228a9b914ad32aa3db88e9de27b0  /tmp/pgvector.tar.gz' \
      | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/pgvector.tar.gz --directory /tmp/pgvector --strip-components=1 \
    && make --directory /tmp/pgvector PG_CONFIG=/usr/lib/postgresql/16/bin/pg_config \
    && make --directory /tmp/pgvector install \
      PG_CONFIG=/usr/lib/postgresql/16/bin/pg_config DESTDIR=/tmp/pgvector-install \
    && rm -rf /var/lib/apt/lists/*

FROM postgres-base
COPY --from=pgvector-builder /tmp/pgvector-install/usr/ /usr/
