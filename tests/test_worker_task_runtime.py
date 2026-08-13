from collections import namedtuple
from typing import Any

from aiops_x_worker import tasks

CacheInfo = namedtuple("CacheInfo", "hits misses maxsize currsize")


class FakeEngine:
    def __init__(self) -> None:
        self.dispose_count = 0

    async def dispose(self) -> None:
        self.dispose_count += 1


class FakeCachedEngineFactory:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self.cached = False
        self.clear_count = 0

    def __call__(self) -> FakeEngine:
        self.cached = True
        return self.engine

    def cache_info(self) -> Any:
        return CacheInfo(0, 0, None, int(self.cached))

    def cache_clear(self) -> None:
        self.cached = False
        self.clear_count += 1


class FakeCachedSessionFactory:
    def __init__(self) -> None:
        self.clear_count = 0

    def cache_clear(self) -> None:
        self.clear_count += 1


def test_worker_releases_async_database_pool_between_event_loops(monkeypatch: Any) -> None:
    engine = FakeEngine()
    engine_factory = FakeCachedEngineFactory(engine)
    session_factory = FakeCachedSessionFactory()

    async def publish_once() -> dict[str, int]:
        engine_factory()
        return {"published": 1, "failed": 0}

    monkeypatch.setattr(tasks, "get_engine", engine_factory)
    monkeypatch.setattr(tasks, "get_session_factory", session_factory)
    monkeypatch.setattr(tasks, "_publish_pending", publish_once)

    assert tasks.publish_event_outbox.run() == {"published": 1, "failed": 0}
    assert tasks.publish_event_outbox.run() == {"published": 1, "failed": 0}
    assert engine.dispose_count == 2
    assert engine_factory.clear_count == 4
    assert session_factory.clear_count == 4
