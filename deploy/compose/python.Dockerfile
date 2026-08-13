ARG PYTHON_IMAGE=python:3.12.4-slim
FROM ${PYTHON_IMAGE} AS python-base

ARG PYPI_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/apps/api/src:/app/apps/worker/src:/app/apps/ai-engine/src:/app/packages/plugin-sdk-python/src \
    PIP_INDEX_URL=${PYPI_INDEX_URL} \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL}

WORKDIR /app

RUN useradd --create-home --uid 10001 aiops
RUN pip install --no-cache-dir uv==0.9.28
COPY --chown=aiops:aiops pyproject.toml uv.lock ./

FROM python-base AS python-runtime
RUN uv export \
        --frozen \
        --no-dev \
        --no-emit-project \
        --format requirements.txt \
        --output-file /tmp/requirements-runtime.txt \
    && uv venv /app/.venv \
    && uv pip sync \
        --python /app/.venv/bin/python \
        --require-hashes \
        --strict \
        /tmp/requirements-runtime.txt

COPY --chown=aiops:aiops alembic.ini ./
COPY --chown=aiops:aiops migrations ./migrations
COPY --chown=aiops:aiops apps/api ./apps/api
COPY --chown=aiops:aiops apps/worker ./apps/worker
COPY --chown=aiops:aiops apps/ai-engine ./apps/ai-engine
COPY --chown=aiops:aiops packages/plugin-sdk-python ./packages/plugin-sdk-python

USER aiops

FROM python-base AS python-quality
RUN uv export \
        --frozen \
        --all-groups \
        --no-emit-project \
        --format requirements.txt \
        --output-file /tmp/requirements-quality.txt \
    && uv venv /app/.venv \
    && uv pip sync \
        --python /app/.venv/bin/python \
        --require-hashes \
        --strict \
        /tmp/requirements-quality.txt
COPY --chown=aiops:aiops alembic.ini ./
COPY --chown=aiops:aiops migrations ./migrations
COPY --chown=aiops:aiops apps ./apps
COPY --chown=aiops:aiops packages/plugin-sdk-python ./packages/plugin-sdk-python
COPY --chown=aiops:aiops tests ./tests
USER aiops
