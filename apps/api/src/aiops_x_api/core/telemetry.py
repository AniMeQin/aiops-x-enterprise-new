from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from aiops_x_api.core.config import get_settings

_provider: TracerProvider | None = None


def configure_tracer_provider() -> TracerProvider | None:
    global _provider
    if _provider is not None:
        return _provider

    settings = get_settings()
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        return None
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        )
    )
    trace.set_tracer_provider(provider)
    RedisInstrumentor().instrument(tracer_provider=provider)
    _provider = provider
    return provider


def configure_fastapi_telemetry(application: FastAPI) -> None:
    provider = configure_tracer_provider()
    if provider is None:
        return
    FastAPIInstrumentor.instrument_app(application, tracer_provider=provider)
