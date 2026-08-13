import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import nats
from aiops_x_api.core.database import get_engine, get_session_factory
from aiops_x_api.modules.audit.application import canonical_audit_document
from aiops_x_api.modules.audit.infrastructure.models import AuditLog, EventOutbox
from aiops_x_api.modules.tenant.infrastructure.models import Project, Tenant  # noqa: F401
from minio import Minio
from minio.commonconfig import GOVERNANCE
from minio.error import S3Error
from minio.retention import Retention
from nats.js.api import StreamConfig
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select

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
