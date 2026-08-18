from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from aiops_x_api.modules.monitoring.contracts import MetricSample
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_alertmanager_normalization_deduplication_event_and_resolution() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    target_labels = {
        "job": "node",
        "instance": "operations-node:9100",
        "aiops_tenant_slug": "operations",
        "aiops_project_slug": "operations-project",
        "aiops_asset_id": "OPS-LINUX-001",
    }

    backend_state = {"observed_at": datetime.now(UTC)}

    class TargetBackend:
        async def instant_query(self, _: str) -> list[MetricSample]:
            return [MetricSample(target_labels, backend_state["observed_at"], 1.0)]

    app.dependency_overrides[get_metrics_backend] = TargetBackend
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/bootstrap",
            headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
            json={
                "tenant_name": "Operations Tenant",
                "tenant_slug": "operations",
                "email": "operations@example.test",
                "display_name": "Operations Admin",
                "password": "Secure-Admin1!",
            },
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": "operations",
                "email": "operations@example.test",
                "password": "Secure-Admin1!",
            },
        )
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        project = client.post(
            "/api/v1/projects",
            headers={**auth, "Idempotency-Key": "operations-project"},
            json={"name": "Operations Project", "slug": "operations-project"},
        ).json()
        asset = client.post(
            "/api/v1/assets",
            headers={**auth, "Idempotency-Key": "operations-asset"},
            json={
                "asset_id": "OPS-LINUX-001",
                "project_id": project["id"],
                "asset_type": "linux",
                "name": "Operations Host",
                "hostname": "operations-node",
                "ip_addresses": ["192.0.2.20"],
                "environment": "test",
            },
        ).json()

        target = client.post(
            "/api/v1/monitoring/targets",
            headers=auth,
            json={
                "project_id": project["id"],
                "asset_id": asset["id"],
                "name": "Operations node exporter",
                "prometheus_job": "node",
                "prometheus_instance": "operations-node:9100",
            },
        )
        assert target.status_code == 201, target.text
        verified = client.post(
            f"/api/v1/monitoring/targets/{target.json()['id']}/verify", headers=auth
        )
        assert verified.status_code == 200, verified.text

        webhook_headers = {"Authorization": "Bearer change-me-development-alertmanager-token"}
        webhook = _webhook(status="firing")
        unauthorized = client.post("/api/v1/webhooks/alertmanager", json=webhook)
        assert unauthorized.status_code == 401

        first = client.post("/api/v1/webhooks/alertmanager", headers=webhook_headers, json=webhook)
        assert first.status_code == 200, first.text
        assert first.json()["created"] == 1
        assert len(first.json()["event_ids"]) == 1

        duplicate = client.post(
            "/api/v1/webhooks/alertmanager", headers=webhook_headers, json=webhook
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["deduplicated"] == 1

        alerts = client.get("/api/v1/alerts", headers=auth)
        assert alerts.status_code == 200
        assert alerts.json()["total"] == 1
        assert alerts.json()["items"][0]["duplicate_count"] == 1
        assert alerts.json()["items"][0]["status"] == "firing"
        alert_id = alerts.json()["items"][0]["id"]

        acknowledged = client.post(
            f"/api/v1/alerts/{alert_id}/actions",
            headers=auth,
            json={"action": "acknowledge", "comment": "Investigating the host"},
        )
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["status"] == "acknowledged"
        assert acknowledged.json()["assigned_to"] is not None
        premature_close = client.post(
            f"/api/v1/alerts/{alert_id}/actions",
            headers=auth,
            json={"action": "close", "resolution_summary": "Not recovered yet"},
        )
        assert premature_close.status_code == 409
        assert premature_close.json()["code"] == "AIOPS_5012"

        events = client.get("/api/v1/events", headers=auth)
        assert events.status_code == 200
        assert events.json()["total"] == 1
        event = events.json()["items"][0]
        assert event["status"] == "open"
        assert event["ai_summary_status"] == "not_configured"

        detail = client.get(f"/api/v1/events/{event['id']}", headers=auth)
        assert detail.status_code == 200
        assert detail.json()["asset"]["id"] == asset["id"]
        assert len(detail.json()["alerts"]) == 1
        assert len(detail.json()["timeline"]) == 2
        assert detail.json()["automation_jobs"] == []
        assert detail.json()["timeline"][0]["evidence_refs"][0]["type"] == ("prometheus_query")

        resolved = client.post(
            "/api/v1/webhooks/alertmanager",
            headers=webhook_headers,
            json=_webhook(status="resolved"),
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["resolved"] == 1
        resolved_event = client.get(f"/api/v1/events/{event['id']}", headers=auth)
        assert resolved_event.json()["status"] == "resolved"
        assert len(resolved_event.json()["timeline"]) == 3
        closed = client.post(
            f"/api/v1/alerts/{alert_id}/actions",
            headers=auth,
            json={
                "action": "close",
                "resolution_summary": "Prometheus confirmed the metric recovered",
            },
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
        assert closed.json()["closed_at"] is not None
        assert [item["action"] for item in closed.json()["timeline"]] == [
            "created",
            "deduplicated",
            "acknowledge",
            "resolved",
            "close",
        ]

        backend_state["observed_at"] = datetime.now(UTC) - timedelta(minutes=10)
        stale = client.post(
            "/api/v1/webhooks/alertmanager",
            headers=webhook_headers,
            json=_webhook(status="firing"),
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "AIOPS_5206"

        backend_state["observed_at"] = datetime.now(UTC)
        wrong_target = _webhook(status="firing")
        wrong_target["alerts"][0]["labels"]["instance"] = "another-node:9100"
        mismatched = client.post(
            "/api/v1/webhooks/alertmanager",
            headers=webhook_headers,
            json=wrong_target,
        )
        assert mismatched.status_code == 422
        assert mismatched.json()["code"] == "AIOPS_5207"

        audits = client.get("/api/v1/audit-logs?page_size=100", headers=auth).json()
        actions = {entry["action"] for entry in audits["items"]}
        assert {
            "alert.created",
            "alert.deduplicated",
            "alert.resolved",
            "event.auto_created",
            "alert.acknowledge",
            "alert.close",
        } <= actions

    app.dependency_overrides.clear()
    await engine.dispose()
    get_settings.cache_clear()


def _webhook(*, status: str) -> dict[str, Any]:
    return {
        "version": "4",
        "status": status,
        "receiver": "aiops-x-control-plane",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "OperationsFlowTest",
                    "severity": "warning",
                    "service": "node-observability",
                    "job": "node",
                    "instance": "operations-node:9100",
                    "aiops_tenant_slug": "operations",
                    "aiops_project_slug": "operations-project",
                    "aiops_asset_id": "OPS-LINUX-001",
                },
                "annotations": {
                    "summary": "Operations flow test",
                    "description": "Real normalized alert fixture",
                    "evidence_query": 'up{job="node"}',
                },
                "startsAt": "2026-08-12T07:00:00Z",
                "endsAt": (
                    "2026-08-12T07:05:00Z" if status == "resolved" else "0001-01-01T00:00:00Z"
                ),
                "generatorURL": "http://prometheus:9090/graph?g0.expr=up",
                "fingerprint": "fixture-source-fingerprint",
            }
        ],
    }
