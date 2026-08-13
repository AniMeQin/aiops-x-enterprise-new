import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.monitoring.contracts import MetricSample


class PrometheusMetricsBackend:
    def __init__(self, base_url: str, *, timeout_seconds: int = 5) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def instant_query(self, query: str) -> list[MetricSample]:
        url = self._base_url + "/api/v1/query?" + urlencode({"query": query})

        def fetch() -> bytes:
            with urlopen(  # noqa: S310 -- configured internal monitoring backend
                url, timeout=self._timeout_seconds
            ) as response:
                return bytes(response.read(1_048_576))

        try:
            document = json.loads(await asyncio.to_thread(fetch))
            if document.get("status") != "success":
                raise ValueError("Prometheus returned non-success status")
            results = document["data"]["result"]
            if not isinstance(results, list):
                raise TypeError("Prometheus result was not a list")
            return [self._sample(item) for item in results]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ApplicationError(
                code="AIOPS_5201",
                message="Prometheus 查询失败",
                status_code=503,
                details={"reason": type(exc).__name__},
            ) from exc

    @staticmethod
    def _sample(item: object) -> MetricSample:
        if not isinstance(item, dict):
            raise TypeError("Prometheus sample was not an object")
        metric = item.get("metric", {})
        value = item.get("value")
        if not isinstance(metric, dict) or not isinstance(value, list) or len(value) != 2:
            raise TypeError("Prometheus sample shape was invalid")
        return MetricSample(
            metric={str(key): str(raw) for key, raw in metric.items()},
            observed_at=datetime.fromtimestamp(float(value[0]), tz=UTC),
            value=float(value[1]),
        )
