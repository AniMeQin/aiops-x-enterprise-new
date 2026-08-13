from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class MetricSample:
    metric: dict[str, str]
    observed_at: datetime
    value: float


class MetricsBackend(Protocol):
    async def instant_query(self, query: str) -> list[MetricSample]: ...
