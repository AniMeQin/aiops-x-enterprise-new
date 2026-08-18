from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from aiops_x_api.modules.monitoring.contracts import MetricPoint, MetricSample, MetricSeries
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from aiops_x_api.modules.monitoring.infrastructure.models import CollectorState
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeMetricsBackend:
    def __init__(
        self,
        *,
        observed_at: datetime,
        labels: dict[str, str],
        duplicate_up: bool = False,
    ) -> None:
        self.observed_at = observed_at
        self.labels = labels
        self.duplicate_up = duplicate_up
        self.queries: list[str] = []

    async def instant_query(self, query: str) -> list[MetricSample]:
        self.queries.append(query)
        if query.startswith("up{"):
            values = [MetricSample(self.labels, self.observed_at, 1.0)]
            return values * (2 if self.duplicate_up else 1)
        value = 12.5 if "node_cpu" in query else 34.5 if "MemAvailable" in query else 56.5
        return [MetricSample(self.labels, self.observed_at, value)]

    async def range_query(
        self, query: str, *, start: datetime, end: datetime, step_seconds: int
    ) -> list[MetricSeries]:
        self.queries.append(query)
        return [
            MetricSeries(
                metric=self.labels,
                points=(
                    MetricPoint(observed_at=start, value=11.0),
                    MetricPoint(observed_at=end, value=22.0),
                ),
            )
        ]


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_node_metrics_require_unique_verified_fresh_asset_binding() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    labels = {
        "job": "node",
        "instance": "node-exporter:9100",
        "aiops_tenant_slug": "monitoring-tenant",
        "aiops_project_slug": "monitoring-project",
        "aiops_asset_id": "MON-LINUX-001",
    }
    backend = FakeMetricsBackend(observed_at=datetime.now(UTC), labels=labels)
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_metrics_backend] = lambda: backend

    with TestClient(app) as client:
        auth, project, asset = _bootstrap_scope(client)

        rule = client.post(
            "/api/v1/monitoring/alert-rules",
            headers=auth,
            json={
                "project_id": project["id"],
                "slug": "host-cpu-high",
                "name": "Host CPU high",
                "metric_key": "cpu",
                "operator": ">",
                "threshold": 85,
                "duration_seconds": 300,
                "severity": "warning",
                "summary": "Host CPU usage is high",
                "description": "CPU remained above the managed threshold",
            },
        )
        assert rule.status_code == 201, rule.text
        assert rule.json()["version"]["status"] == "draft"
        assert 'aiops_tenant_slug="monitoring-tenant"' in rule.json()["version"]["expression"]
        version = client.post(
            f"/api/v1/monitoring/alert-rules/{rule.json()['id']}/versions",
            headers=auth,
            json={
                "metric_key": "cpu",
                "operator": ">",
                "threshold": 90,
                "duration_seconds": 600,
                "severity": "critical",
                "summary": "Host CPU usage is critical",
                "description": "CPU remained above the critical threshold",
            },
        )
        assert version.status_code == 201, version.text
        published = client.post(
            f"/api/v1/monitoring/alert-rules/{rule.json()['id']}/versions/2/publish",
            headers=auth,
        )
        assert published.status_code == 200, published.text
        assert published.json()["published_version"] == 2
        assert published.json()["version"]["status"] == "published"

        unbound = client.get(f"/api/v1/monitoring/assets/{asset['id']}/node-metrics", headers=auth)
        assert unbound.status_code == 409
        assert unbound.json()["code"] == "AIOPS_5204"
        assert unbound.json()["details"]["status"] == "not_configured"

        target = client.post(
            "/api/v1/monitoring/targets",
            headers=auth,
            json={
                "project_id": project["id"],
                "asset_id": asset["id"],
                "name": "Monitoring node exporter",
                "target_type": "node_exporter",
                "prometheus_job": "node",
                "prometheus_instance": "node-exporter:9100",
            },
        )
        assert target.status_code == 201, target.text
        target_body = target.json()
        assert target_body["binding"]["identity_value"] == "MON-LINUX-001"
        assert target_body["binding"]["verification_status"] == "unverified"

        unrelated_target = client.patch(
            f"/api/v1/monitoring/targets/{target_body['id']}",
            headers=auth,
            json={"prometheus_instance": "unrelated.example.test:9100"},
        )
        assert unrelated_target.status_code == 422
        assert unrelated_target.json()["code"] == "AIOPS_5215"

        duplicate = client.post(
            "/api/v1/monitoring/targets",
            headers=auth,
            json={
                "project_id": project["id"],
                "asset_id": asset["id"],
                "name": "Duplicate binding",
                "prometheus_job": "node",
                "prometheus_instance": "node-exporter:9200",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "AIOPS_5211"

        verified = client.post(
            f"/api/v1/monitoring/targets/{target_body['id']}/verify", headers=auth
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["status"] == "verified"
        assert verified.json()["target_up"] is True

        metrics = client.get(f"/api/v1/monitoring/assets/{asset['id']}/node-metrics", headers=auth)
        assert metrics.status_code == 200, metrics.text
        body = metrics.json()
        assert body["target_id"] == target_body["id"]
        assert body["binding_id"] == target_body["binding"]["id"]
        assert body["freshness_status"] == "fresh"
        assert body["target_up"] is True
        assert body["cpu_usage_percent"] == 12.5
        assert body["memory_usage_percent"] == 34.5
        assert body["root_filesystem_usage_percent"] == 56.5
        assert "prometheus_url" not in body
        assert all('aiops_asset_id="MON-LINUX-001"' in query for query in backend.queries)

        history = client.get(
            f"/api/v1/monitoring/assets/{asset['id']}/node-metrics/history",
            headers=auth,
            params={
                "metric": "cpu",
                "start": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "end": datetime.now(UTC).isoformat(),
                "step_seconds": 60,
            },
        )
        assert history.status_code == 200, history.text
        assert history.json()["source"] == "prometheus"
        assert history.json()["metric_name"] == "cpu"
        assert [point["value"] for point in history.json()["series"][0]["points"]] == [
            11.0,
            22.0,
        ]

        oversized_history = client.get(
            f"/api/v1/monitoring/assets/{asset['id']}/node-metrics/history",
            headers=auth,
            params={
                "metric": "cpu",
                "start": (datetime.now(UTC) - timedelta(days=8)).isoformat(),
                "end": datetime.now(UTC).isoformat(),
            },
        )
        assert oversized_history.status_code == 422
        assert oversized_history.json()["code"] == "AIOPS_5214"

        current_asset = client.get(f"/api/v1/assets/{asset['id']}", headers=auth).json()
        assert current_asset["monitoring_status"] == "active"
        assert current_asset["last_monitored_at"] is not None

        async with factory() as session:
            collector_state = await session.scalar(
                select(CollectorState).where(CollectorState.asset_id == UUID(asset["id"]))
            )
            assert collector_state is not None
            assert collector_state.status == "healthy"
            assert collector_state.consecutive_failures == 0
            assert collector_state.last_sample_at is not None

        targets = client.get("/api/v1/monitoring/targets", headers=auth)
        assert targets.status_code == 200
        assert targets.json()["items"][0]["binding"]["verification_status"] == "verified"

    app.dependency_overrides.clear()
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_target_verification_fails_closed_for_stale_duplicate_or_wrong_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    correct_labels = {
        "job": "node",
        "instance": "node-exporter:9100",
        "aiops_tenant_slug": "monitoring-tenant",
        "aiops_project_slug": "monitoring-project",
        "aiops_asset_id": "MON-LINUX-001",
    }
    current_backend: dict[str, FakeMetricsBackend] = {
        "value": FakeMetricsBackend(
            observed_at=datetime.now(UTC) - timedelta(minutes=10), labels=correct_labels
        )
    }
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_metrics_backend] = lambda: current_backend["value"]

    with TestClient(app) as client:
        auth, project, asset = _bootstrap_scope(client)
        target = client.post(
            "/api/v1/monitoring/targets",
            headers=auth,
            json={
                "project_id": project["id"],
                "asset_id": asset["id"],
                "name": "Monitoring node exporter",
                "prometheus_job": "node",
                "prometheus_instance": "node-exporter:9100",
            },
        ).json()

        stale = client.post(f"/api/v1/monitoring/targets/{target['id']}/verify", headers=auth)
        assert stale.status_code == 409
        assert stale.json()["code"] == "AIOPS_5206"

        current_backend["value"] = FakeMetricsBackend(
            observed_at=datetime.now(UTC), labels=correct_labels, duplicate_up=True
        )
        duplicate = client.post(f"/api/v1/monitoring/targets/{target['id']}/verify", headers=auth)
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "AIOPS_5205"

        wrong = {**correct_labels, "aiops_asset_id": "OTHER-ASSET"}
        current_backend["value"] = FakeMetricsBackend(observed_at=datetime.now(UTC), labels=wrong)
        mismatched = client.post(f"/api/v1/monitoring/targets/{target['id']}/verify", headers=auth)
        assert mismatched.status_code == 409
        assert mismatched.json()["code"] == "AIOPS_5207"

        targets = client.get("/api/v1/monitoring/targets", headers=auth).json()
        assert targets["items"][0]["binding"]["verification_status"] == "failed"
        assert targets["items"][0]["binding"]["last_error_code"] == "AIOPS_5207"

    app.dependency_overrides.clear()
    await engine.dispose()
    get_settings.cache_clear()


def _bootstrap_scope(client: TestClient) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
        json={
            "tenant_name": "Monitoring Tenant",
            "tenant_slug": "monitoring-tenant",
            "email": "monitoring@example.test",
            "display_name": "Monitoring Admin",
            "password": "Secure-Monitor1!",
        },
    )
    assert bootstrap.status_code == 201, bootstrap.text
    login = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "monitoring-tenant",
            "email": "monitoring@example.test",
            "password": "Secure-Monitor1!",
        },
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    project = client.post(
        "/api/v1/projects",
        headers={**auth, "Idempotency-Key": "monitoring-project"},
        json={"name": "Monitoring Project", "slug": "monitoring-project"},
    ).json()
    asset = client.post(
        "/api/v1/assets",
        headers={**auth, "Idempotency-Key": "monitoring-asset"},
        json={
            "asset_id": "MON-LINUX-001",
            "project_id": project["id"],
            "asset_type": "linux",
            "name": "Monitoring Linux Host",
            "hostname": "node-exporter",
            "ip_addresses": ["192.0.2.30"],
            "environment": "test",
        },
    ).json()
    return auth, project, asset
