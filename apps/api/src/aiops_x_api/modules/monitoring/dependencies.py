from aiops_x_api.core.config import get_settings
from aiops_x_api.modules.monitoring.adapters import PrometheusMetricsBackend
from aiops_x_api.modules.monitoring.contracts import MetricsBackend


def get_metrics_backend() -> MetricsBackend:
    return PrometheusMetricsBackend(get_settings().prometheus_url)
