import json
from collections import namedtuple
from pathlib import Path
from typing import Any
from uuid import uuid4

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


def test_prometheus_file_sd_write_is_atomic_and_machine_readable(tmp_path: Path) -> None:
    target_path = tmp_path / "targets" / "targets.json"
    document = [
        {
            "targets": ["10.20.30.40:9100"],
            "labels": {
                "aiops_tenant_slug": "tenant",
                "aiops_project_slug": "project",
                "aiops_asset_id": "ASSET-001",
            },
        }
    ]
    tasks._atomic_write_json(target_path, document)
    assert json.loads(target_path.read_text(encoding="utf-8")) == document
    assert not list(target_path.parent.glob(".targets-*"))


def test_managed_rule_renderer_emits_versioned_prometheus_contract() -> None:
    document = tasks.render_prometheus_rules(
        [
            tasks.PublishedRuleDocument(
                rule_id=uuid4(),
                slug="host-cpu-high",
                version=2,
                expression='up{aiops_asset_id="ASSET-001"} == 0',
                duration_seconds=300,
                labels={"severity": "critical"},
                annotations={"summary": "Host down"},
            )
        ]
    )
    rule = document["groups"][0]["rules"][0]
    assert rule["alert"] == "AIOpsX_host_cpu_high_v2"
    assert rule["for"] == "300s"
    assert rule["labels"] == {"severity": "critical"}
