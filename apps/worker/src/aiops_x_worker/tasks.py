import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID

import nats
from aiops_x_api.core.database import get_engine, get_session_factory
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.audit.application import append_audit, canonical_audit_document
from aiops_x_api.modules.audit.infrastructure.models import AuditLog, EventOutbox
from aiops_x_api.modules.cmdb.infrastructure.models import Asset  # noqa: F401
from aiops_x_api.modules.discovery.adapters import AsyncTcpDiscoveryBackend
from aiops_x_api.modules.discovery.application import (
    claim_scheduled_run,
    collect_observations,
    complete_run,
    fail_run,
    get_job,
    get_run,
)
from aiops_x_api.modules.monitoring.infrastructure.models import (
    AlertRule,
    AlertRuleVersion,
    AssetMonitorBinding,
    MonitorTarget,
)
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant  # noqa: F401
from minio import Minio
from minio.commonconfig import GOVERNANCE
from minio.error import S3Error
from minio.retention import Retention
from nats.js.api import StreamConfig
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from aiops_x_worker.celery_app import celery_app

OUTBOX_PUBLISHED = Counter(
    "aiops_x_outbox_published_total", "Outbox events published to JetStream."
)
OUTBOX_FAILED = Counter(
    "aiops_x_outbox_publish_failures_total", "Outbox publication attempts that failed."
)
OUTBOX_PENDING = Gauge("aiops_x_outbox_pending", "Pending transactional outbox events.")
AUDIT_ARCHIVED = Counter(
    "aiops_x_audit_archived_total", "Audit entries archived to immutable object storage."
)
AUDIT_ARCHIVE_FAILED = Counter(
    "aiops_x_audit_archive_failures_total", "Audit WORM archive failures."
)
JETSTREAM_CONSUMED = Counter(
    "aiops_x_jetstream_consumed_total", "Versioned events validated by the observability consumer."
)
JETSTREAM_REJECTED = Counter(
    "aiops_x_jetstream_rejected_total", "Invalid versioned events rejected by the consumer."
)
JETSTREAM_CONSUMER_LAG = Gauge(
    "aiops_x_jetstream_consumer_lag",
    "Pending and unacknowledged messages for the observability durable consumer.",
    ("stream", "consumer"),
)
PROMETHEUS_TARGETS_CONFIGURED = Gauge(
    "aiops_x_prometheus_targets_configured",
    "Enabled and uniquely bound Prometheus targets published to file_sd.",
)
PROMETHEUS_TARGET_SYNC_FAILED = Counter(
    "aiops_x_prometheus_target_sync_failures_total",
    "Prometheus file_sd publication failures.",
)
PROMETHEUS_RULES_CONFIGURED = Gauge(
    "aiops_x_prometheus_rules_configured", "Published managed Prometheus alert rules."
)
PROMETHEUS_RULE_SYNC_FAILED = Counter(
    "aiops_x_prometheus_rule_sync_failures_total", "Prometheus rule sync or reload failures."
)
DISCOVERY_SCHEDULED_RUNS = Counter(
    "aiops_x_discovery_scheduled_runs_total",
    "Scheduled discovery runs by terminal outcome.",
    ("outcome",),
)


@dataclass(frozen=True)
class ScheduledDiscoveryScope:
    tenant_id: UUID
    project_id: UUID
    job_id: UUID
    run_id: UUID
    networks: tuple[str, ...]
    ports: tuple[int, ...]
    timeout_seconds: float
    max_hosts: int


@dataclass(frozen=True)
class PublishedRuleDocument:
    rule_id: UUID
    slug: str
    version: int
    expression: str
    duration_seconds: int
    labels: dict[str, str]
    annotations: dict[str, str]


@celery_app.task(name="aiops_x_worker.sync_prometheus_rules")  # type: ignore[untyped-decorator]
def sync_prometheus_rules() -> dict[str, int]:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return asyncio.run(_sync_prometheus_rules_with_database_cleanup())


async def _sync_prometheus_rules_with_database_cleanup() -> dict[str, int]:
    try:
        return await _sync_prometheus_rules()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()


async def _sync_prometheus_rules() -> dict[str, int]:
    from aiops_x_api.core.config import get_settings

    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(AlertRule, AlertRuleVersion)
                .join(
                    AlertRuleVersion,
                    (AlertRuleVersion.alert_rule_id == AlertRule.id)
                    & (AlertRuleVersion.version == AlertRule.published_version),
                )
                .where(
                    AlertRule.enabled.is_(True),
                    AlertRuleVersion.status == "published",
                )
                .order_by(AlertRule.tenant_id, AlertRule.project_id, AlertRule.slug)
                .limit(10_000)
            )
        ).all()
    rules = [
        PublishedRuleDocument(
            rule_id=rule.id,
            slug=rule.slug,
            version=version.version,
            expression=version.expression,
            duration_seconds=version.duration_seconds,
            labels=dict(version.labels),
            annotations=dict(version.annotations),
        )
        for rule, version in rows
    ]
    settings = get_settings()
    try:
        await asyncio.to_thread(
            _atomic_write_json,
            Path(settings.prometheus_rule_file_path),
            render_prometheus_rules(rules),
        )
        await asyncio.to_thread(_reload_prometheus, settings.prometheus_reload_url)
    except OSError:
        PROMETHEUS_RULE_SYNC_FAILED.inc()
        raise
    PROMETHEUS_RULES_CONFIGURED.set(len(rules))
    return {"published": len(rules)}


def render_prometheus_rules(rules: list[PublishedRuleDocument]) -> dict[str, object]:
    return {
        "groups": [
            {
                "name": "aiops-x-managed",
                "rules": [
                    {
                        "alert": "AIOpsX_" + rule.slug.replace("-", "_") + f"_v{rule.version}",
                        "expr": rule.expression,
                        "for": f"{rule.duration_seconds}s",
                        "labels": rule.labels,
                        "annotations": rule.annotations,
                    }
                    for rule in rules
                ],
            }
        ]
    }


def _reload_prometheus(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OSError("Prometheus reload URL is invalid")
    request = UrlRequest(url, data=b"", method="POST")  # noqa: S310 -- validated above
    with urlopen(request, timeout=5) as response:  # noqa: S310 -- internal configured service
        if response.status != 200:
            raise OSError("Prometheus reload was rejected")


@celery_app.task(name="aiops_x_worker.run_scheduled_discovery")  # type: ignore[untyped-decorator]
def run_scheduled_discovery() -> dict[str, int]:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return asyncio.run(_scheduled_discovery_with_database_cleanup())


async def _scheduled_discovery_with_database_cleanup() -> dict[str, int]:
    try:
        return await _run_one_scheduled_discovery()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()


async def _run_one_scheduled_discovery() -> dict[str, int]:
    async with get_session_factory()() as session:
        async with session.begin():
            claimed = await claim_scheduled_run(session, now=datetime.now(UTC))
            if claimed is None:
                return {"claimed": 0, "succeeded": 0, "failed": 0}
            job, run = claimed
            scope = ScheduledDiscoveryScope(
                tenant_id=job.tenant_id,
                project_id=job.project_id,
                job_id=job.id,
                run_id=run.id,
                networks=tuple(job.networks),
                ports=tuple(job.ports),
                timeout_seconds=job.timeout_seconds,
                max_hosts=job.max_hosts,
            )
        try:
            observations = await collect_observations(
                networks=scope.networks,
                ports=scope.ports,
                timeout_seconds=scope.timeout_seconds,
                max_hosts=scope.max_hosts,
                backend=AsyncTcpDiscoveryBackend(),
            )
            async with session.begin():
                job = await get_job(
                    session,
                    tenant_id=scope.tenant_id,
                    job_id=scope.job_id,
                )
                run = await get_run(
                    session,
                    tenant_id=scope.tenant_id,
                    run_id=scope.run_id,
                )
                await complete_run(session, job=job, run=run, observations=observations)
                await _append_worker_discovery_audit(
                    session,
                    tenant_id=scope.tenant_id,
                    project_id=scope.project_id,
                    run_id=scope.run_id,
                    outcome="success",
                    metadata={"candidate_count": run.candidate_count},
                )
        except ApplicationError as error:
            await _record_scheduled_discovery_failure(session, scope=scope, error_code=error.code)
            DISCOVERY_SCHEDULED_RUNS.labels("failure").inc()
            return {"claimed": 1, "succeeded": 0, "failed": 1}
        except Exception:
            await _record_scheduled_discovery_failure(session, scope=scope, error_code="AIOPS_3313")
            DISCOVERY_SCHEDULED_RUNS.labels("failure").inc()
            return {"claimed": 1, "succeeded": 0, "failed": 1}
    DISCOVERY_SCHEDULED_RUNS.labels("success").inc()
    return {"claimed": 1, "succeeded": 1, "failed": 0}


async def _record_scheduled_discovery_failure(
    session: AsyncSession, *, scope: ScheduledDiscoveryScope, error_code: str
) -> None:
    async with session.begin():
        await fail_run(
            session,
            tenant_id=scope.tenant_id,
            job_id=scope.job_id,
            run_id=scope.run_id,
            error_code=error_code,
        )
        await _append_worker_discovery_audit(
            session,
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            run_id=scope.run_id,
            outcome="failure",
            metadata={"error_code": error_code},
        )


async def _append_worker_discovery_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    run_id: UUID,
    outcome: str,
    metadata: dict[str, object],
) -> None:
    request = Request(
        {
            "type": "http",
            "method": "WORKER",
            "path": "/internal/scheduled-discovery",
            "headers": [],
            "query_string": b"",
            "scheme": "internal",
            "server": None,
            "client": None,
        }
    )
    await append_audit(
        session,
        request,
        action="discovery.run.completed",
        resource_type="discovery_run",
        outcome=outcome,
        actor_type="service",
        actor_id="aiops-x-worker",
        tenant_id=tenant_id,
        project_id=project_id,
        resource_id=str(run_id),
        metadata=metadata,
        producer="aiops-x-worker",
    )


@celery_app.task(name="aiops_x_worker.sync_prometheus_targets")  # type: ignore[untyped-decorator]
def sync_prometheus_targets() -> dict[str, int]:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return asyncio.run(_sync_prometheus_targets_with_database_cleanup())


async def _sync_prometheus_targets_with_database_cleanup() -> dict[str, int]:
    try:
        return await _sync_prometheus_targets()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()


async def _sync_prometheus_targets() -> dict[str, int]:
    from aiops_x_api.core.config import get_settings

    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(MonitorTarget, AssetMonitorBinding)
                .join(
                    AssetMonitorBinding,
                    AssetMonitorBinding.monitor_target_id == MonitorTarget.id,
                )
                .where(
                    MonitorTarget.enabled.is_(True),
                    MonitorTarget.target_type == "node_exporter",
                    MonitorTarget.prometheus_job == "node",
                    AssetMonitorBinding.enabled.is_(True),
                    AssetMonitorBinding.purpose == "node_metrics",
                )
                .order_by(MonitorTarget.id)
                .limit(10_000)
            )
        ).all()
    document = [
        {
            "targets": [target.prometheus_instance],
            "labels": {
                "aiops_tenant_slug": target.tenant_slug,
                "aiops_project_slug": target.project_slug,
                binding.identity_label: binding.identity_value,
            },
        }
        for target, binding in rows
    ]
    try:
        await asyncio.to_thread(
            _atomic_write_json,
            Path(get_settings().prometheus_target_file_path),
            document,
        )
    except OSError:
        PROMETHEUS_TARGET_SYNC_FAILED.inc()
        raise
    PROMETHEUS_TARGETS_CONFIGURED.set(len(document))
    return {"published": len(document)}


def _atomic_write_json(path: Path, document: object) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    content = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".targets-", delete=False
    ) as temporary:
        temporary.write(content)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o640)
    os.replace(temporary_path, path)


@celery_app.task(name="aiops_x_worker.publish_event_outbox")  # type: ignore[untyped-decorator]
def publish_event_outbox() -> dict[str, int]:
    # Each Celery task invocation creates a new asyncio event loop. SQLAlchemy's
    # asyncpg pool must therefore be created and disposed within that same loop.
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return asyncio.run(_publish_pending_with_database_cleanup())


@celery_app.task(name="aiops_x_worker.consume_event_observability")  # type: ignore[untyped-decorator]
def consume_event_observability() -> dict[str, int]:
    """Validate the v1 envelope on a real durable JetStream consumer.

    This consumer is deliberately side-effect free. Domain consumers may attach
    their own durable name, while this one proves delivery and exposes real lag.
    """
    return asyncio.run(_consume_event_observability())


async def _consume_event_observability() -> dict[str, int]:
    from aiops_x_api.core.config import get_settings

    stream = "AIOPS_EVENTS_V1"
    durable = "AIOPS_OBSERVABILITY_V1"
    connection = await nats.connect(
        get_settings().nats_url, connect_timeout=2, max_reconnect_attempts=2
    )
    consumed = 0
    rejected = 0
    try:
        jetstream = connection.jetstream()
        try:
            subscription = await jetstream.pull_subscribe(
                "aiops.events.v1.>", durable=durable, stream=stream
            )
            messages = await subscription.fetch(batch=100, timeout=0.5)
        except nats.js.errors.NotFoundError:
            JETSTREAM_CONSUMER_LAG.labels(stream, durable).set(0)
            return {"consumed": 0, "rejected": 0, "lag": 0}
        except nats.errors.TimeoutError:
            messages = []
        for message in messages:
            try:
                payload = json.loads(message.data)
                _validate_event_envelope(payload)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                rejected += 1
            else:
                consumed += 1
            # Invalid events are acknowledged after being counted so a poison
            # message cannot block the durable consumer indefinitely.
            await message.ack()
        info = await jetstream.consumer_info(stream, durable)
        lag = int(info.num_pending) + int(info.num_ack_pending)
        JETSTREAM_CONSUMER_LAG.labels(stream, durable).set(lag)
    finally:
        await connection.drain()
    JETSTREAM_CONSUMED.inc(consumed)
    JETSTREAM_REJECTED.inc(rejected)
    return {"consumed": consumed, "rejected": rejected, "lag": lag}


def _validate_event_envelope(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("event envelope must be an object")
    required = {
        "event_id",
        "event_type",
        "event_version",
        "occurred_at",
        "tenant_id",
        "producer",
        "trace_id",
        "data",
    }
    if required - payload.keys() or payload.get("event_version") != 1:
        raise ValueError("unsupported event envelope")
    if not isinstance(payload.get("data"), dict):
        raise ValueError("event data must be an object")


async def _publish_pending_with_database_cleanup() -> dict[str, int]:
    try:
        return await _publish_pending()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()


async def _publish_pending() -> dict[str, int]:
    from aiops_x_api.core.config import get_settings

    settings = get_settings()
    connection = await nats.connect(
        settings.nats_url,
        connect_timeout=2,
        max_reconnect_attempts=2,
    )
    published = 0
    failed = 0
    pending = 0
    try:
        jetstream = connection.jetstream()
        try:
            await jetstream.stream_info("AIOPS_EVENTS_V1")
        except nats.js.errors.NotFoundError:
            await jetstream.add_stream(
                config=StreamConfig(
                    name="AIOPS_EVENTS_V1",
                    subjects=["aiops.events.v1.>"],
                    max_age=timedelta(days=7).total_seconds(),
                )
            )
        now = datetime.now(UTC)
        async with get_session_factory()() as session, session.begin():
            rows = (
                await session.scalars(
                    select(EventOutbox)
                    .where(
                        EventOutbox.status == "pending",
                        EventOutbox.next_attempt_at <= now,
                    )
                    .order_by(EventOutbox.created_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                try:
                    await jetstream.publish(
                        row.subject,
                        json.dumps(row.payload, separators=(",", ":")).encode(),
                        headers={"Nats-Msg-Id": str(row.id)},
                    )
                    row.status = "published"
                    row.published_at = datetime.now(UTC)
                    row.last_error = None
                    published += 1
                except (nats.errors.Error, TimeoutError) as error:
                    row.attempts += 1
                    row.last_error = type(error).__name__
                    row.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=min(2**row.attempts, 300)
                    )
                    failed += 1
            pending = (
                await session.scalar(
                    select(func.count())
                    .select_from(EventOutbox)
                    .where(EventOutbox.status == "pending")
                )
                or 0
            )
    finally:
        await connection.drain()
    OUTBOX_PUBLISHED.inc(published)
    OUTBOX_FAILED.inc(failed)
    OUTBOX_PENDING.set(pending)
    return {"published": published, "failed": failed}


@celery_app.task(name="aiops_x_worker.archive_audit_worm")  # type: ignore[untyped-decorator]
def archive_audit_worm() -> dict[str, int]:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    return asyncio.run(_archive_audit_with_database_cleanup())


async def _archive_audit_with_database_cleanup() -> dict[str, int]:
    try:
        return await _archive_audit_entries()
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()


async def _archive_audit_entries() -> dict[str, int]:
    from aiops_x_api.core.config import get_settings

    settings = get_settings()
    archived = 0
    failed = 0
    now = datetime.now(UTC)
    async with get_session_factory()() as session, session.begin():
        rows = (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.archived_at.is_(None))
                .order_by(AuditLog.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            content = json.dumps(
                {
                    "schema": "aiops-x.audit.v1",
                    "entry_hash": row.entry_hash,
                    "record": canonical_audit_document(row),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            if (
                hashlib.sha256(
                    json.dumps(
                        canonical_audit_document(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                != row.entry_hash
            ):
                failed += 1
                continue
            object_name = (
                f"tenant/{row.partition_key}/{row.created_at:%Y/%m/%d}/"
                f"{row.sequence_no:020d}-{row.id}.json"
            )
            try:
                object_ref = await asyncio.to_thread(
                    _put_worm_object,
                    settings.minio_endpoint,
                    settings.minio_access_key.get_secret_value(),
                    settings.minio_secret_key.get_secret_value(),
                    settings.minio_secure,
                    settings.audit_archive_bucket,
                    object_name,
                    content,
                    now + timedelta(days=settings.audit_retention_days),
                )
            except (S3Error, OSError, ValueError):
                failed += 1
                continue
            row.archive_object_ref = object_ref
            row.archived_at = now
            archived += 1
    AUDIT_ARCHIVED.inc(archived)
    AUDIT_ARCHIVE_FAILED.inc(failed)
    return {"archived": archived, "failed": failed}


def _put_worm_object(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool,
    bucket: str,
    object_name: str,
    content: bytes,
    retain_until: datetime,
) -> str:
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket, object_lock=True)
    client.put_object(
        bucket,
        object_name,
        BytesIO(content),
        len(content),
        content_type="application/json",
        retention=Retention(GOVERNANCE, retain_until),
    )
    return f"s3://{bucket}/{object_name}"
