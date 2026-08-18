from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class MetricSample:
    metric: dict[str, str]
    observed_at: datetime
    value: float


@dataclass(frozen=True)
class MetricPoint:
    observed_at: datetime
    value: float


@dataclass(frozen=True)
class MetricSeries:
    metric: dict[str, str]
    points: tuple[MetricPoint, ...]


class MetricsBackend(Protocol):
    async def instant_query(self, query: str) -> list[MetricSample]: ...

    async def range_query(
        self, query: str, *, start: datetime, end: datetime, step_seconds: int
    ) -> list[MetricSeries]: ...
