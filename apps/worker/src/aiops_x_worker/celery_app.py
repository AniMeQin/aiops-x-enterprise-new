from aiops_x_api.core.config import get_settings
from aiops_x_api.core.telemetry import configure_tracer_provider
from celery import Celery
from opentelemetry.instrumentation.celery import CeleryInstrumentor

from aiops_x_worker.monitoring import start_monitoring_server

settings = get_settings()
broker_url = settings.redis_url.get_secret_value()
tracer_provider = configure_tracer_provider()
if tracer_provider is not None:
    CeleryInstrumentor().instrument(  # type: ignore[no-untyped-call]
        tracer_provider=tracer_provider
    )

celery_app = Celery("aiops_x_worker", broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "publish-event-outbox": {
            "task": "aiops_x_worker.publish_event_outbox",
            "schedule": 5.0,
        },
        "archive-audit-worm": {
            "task": "aiops_x_worker.archive_audit_worm",
            "schedule": 60.0,
        },
        "consume-event-observability": {
            "task": "aiops_x_worker.consume_event_observability",
            "schedule": 5.0,
        },
    },
)
start_monitoring_server()

from aiops_x_worker import tasks as _tasks  # noqa: E402,F401
