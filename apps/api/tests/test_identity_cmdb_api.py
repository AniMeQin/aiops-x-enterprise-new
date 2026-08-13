from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from aiops_x_api.modules.agent_control.infrastructure.models import EdgeAgent
from aiops_x_api.modules.audit.infrastructure.models import EventOutbox
from aiops_x_api.modules.identity.security import hash_password, verify_password
from aiops_x_api.modules.monitoring.contracts import MetricSample
from aiops_x_api.modules.monitoring.dependencies import get_metrics_backend
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("Secure-Admin1!")
    second = hash_password("Secure-Admin1!")

    assert first != second
    assert "Secure-Admin1!" not in first
    assert verify_password("Secure-Admin1!", first)
    assert not verify_password("wrong-password", first)


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_bootstrap_login_project_asset_and_audit_are_real_database_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_test_agent_pki(tmp_path, monkeypatch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session

    class IntegrationMetricsBackend:
        async def instant_query(self, _: str) -> list[MetricSample]:
            return [
                MetricSample(
                    metric={
                        "job": "node",
                        "instance": "integration-host:9100",
                        "aiops_tenant_slug": "api-integration",
                        "aiops_project_slug": "authorized-test",
                        "aiops_asset_id": "TEST-LINUX-001",
                    },
                    observed_at=datetime.now(UTC),
                    value=1.0,
                )
            ]

    app.dependency_overrides[get_metrics_backend] = IntegrationMetricsBackend
    with TestClient(app) as client:
        status = client.get("/api/v1/auth/bootstrap/status")
        assert status.status_code == 200
        assert status.json() == {"required": True}

        bootstrap = client.post(
            "/api/v1/auth/bootstrap",
            headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
            json={
                "tenant_name": "API Integration Tenant",
                "tenant_slug": "api-integration",
                "email": "admin@example.test",
                "display_name": "Integration Admin",
                "password": "Secure-Admin1!",
            },
        )
        assert bootstrap.status_code == 201, bootstrap.text
        assert bootstrap.json()["is_bootstrap_admin"] is True

        second_bootstrap = client.post(
            "/api/v1/auth/bootstrap",
            headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
            json={
                "tenant_name": "Rejected",
                "tenant_slug": "rejected-tenant",
                "email": "other@example.test",
                "display_name": "Rejected User",
                "password": "Secure-Admin2!",
            },
        )
        assert second_bootstrap.status_code == 409

        login = client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": "api-integration",
                "email": "admin@example.test",
                "password": "Secure-Admin1!",
            },
        )
        assert login.status_code == 200, login.text
        tokens = login.json()
        access_token = tokens["access_token"]
        admin_refresh_cookie = client.cookies.get("aiops_x_refresh")
        auth = {"Authorization": f"Bearer {access_token}"}

        me = client.get("/api/v1/auth/me", headers=auth)
        assert me.status_code == 200
        assert me.json()["roles"] == ["platform_admin"]

        project = client.post(
            "/api/v1/projects",
            headers={**auth, "Idempotency-Key": "project-integration-1"},
            json={"name": "Authorized Test Project", "slug": "authorized-test"},
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]
        assert client.get(f"/api/v1/projects/{project_id}", headers=auth).status_code == 200
        updated_project = client.patch(
            f"/api/v1/projects/{project_id}",
            headers=auth,
            json={"name": "Authorized Test Project Updated"},
        )
        assert updated_project.status_code == 200, updated_project.text
        assert updated_project.json()["name"].endswith("Updated")

        asset = client.post(
            "/api/v1/assets",
            headers={**auth, "Idempotency-Key": "asset-integration-1"},
            json={
                "asset_id": "TEST-LINUX-001",
                "project_id": project_id,
                "asset_type": "linux",
                "name": "Integration Linux Host",
                "hostname": "integration-host",
                "ip_addresses": ["192.0.2.10"],
                "environment": "test",
                "criticality": "low",
                "gxp_classification": "unclassified",
                "credential_ref": "vault://kv/integration/host/ssh",
                "tags": ["integration"],
            },
        )
        assert asset.status_code == 201, asset.text
        assert asset.json()["credential_configured"] is True
        assert "credential_ref" not in asset.text
        assert asset.json()["monitoring_status"] == "not_configured"
        assert "password" not in asset.text.lower()
        asset_id = asset.json()["id"]
        assert client.get(f"/api/v1/assets/{asset_id}", headers=auth).status_code == 200
        updated_asset = client.patch(
            f"/api/v1/assets/{asset_id}",
            headers=auth,
            json={"owner": "SRE", "tags": ["integration", "managed"]},
        )
        assert updated_asset.status_code == 200, updated_asset.text
        assert updated_asset.json()["owner"] == "SRE"

        target_asset = client.post(
            "/api/v1/assets",
            headers=auth,
            json={
                "asset_id": "TEST-APP-001",
                "project_id": project_id,
                "asset_type": "application",
                "name": "Integration Application",
                "environment": "test",
            },
        )
        assert target_asset.status_code == 201, target_asset.text
        target_asset_id = target_asset.json()["id"]
        relation = client.post(
            f"/api/v1/assets/{target_asset_id}/relations",
            headers=auth,
            json={
                "target_asset_id": asset_id,
                "relation_type": "RUNS_ON",
                "source": "integration-test",
                "confidence": "high",
                "manually_confirmed": True,
            },
        )
        assert relation.status_code == 201, relation.text
        relation_id = relation.json()["id"]
        incoming = client.get(
            f"/api/v1/assets/{asset_id}/relations?direction=incoming", headers=auth
        )
        assert incoming.status_code == 200, incoming.text
        assert incoming.json()["total"] == 1
        assert incoming.json()["items"][0]["relation_type"] == "RUNS_ON"
        duplicate_relation = client.post(
            f"/api/v1/assets/{target_asset_id}/relations",
            headers=auth,
            json={
                "target_asset_id": asset_id,
                "relation_type": "RUNS_ON",
                "source": "integration-test",
            },
        )
        assert duplicate_relation.status_code == 409
        self_relation = client.post(
            f"/api/v1/assets/{asset_id}/relations",
            headers=auth,
            json={
                "target_asset_id": asset_id,
                "relation_type": "DEPENDS_ON",
                "source": "integration-test",
            },
        )
        assert self_relation.status_code == 422
        expired = client.delete(
            f"/api/v1/assets/{target_asset_id}/relations/{relation_id}", headers=auth
        )
        assert expired.status_code == 204
        assert (
            client.get(
                f"/api/v1/assets/{asset_id}/relations?direction=incoming", headers=auth
            ).json()["total"]
            == 0
        )
        historical_relations = client.get(
            f"/api/v1/assets/{asset_id}/relations?direction=incoming&active_only=false",
            headers=auth,
        )
        assert historical_relations.json()["total"] == 1

        role = client.post(
            "/api/v1/auth/roles",
            headers=auth,
            json={
                "name": "operations_viewer",
                "description": "Read-only operations role",
                "permissions": [
                    "asset:read",
                    "project:read",
                    "agent:read",
                    "metrics:read",
                    "alert:read",
                    "event:read",
                    "runbook:read",
                    "job:read",
                ],
            },
        )
        assert role.status_code == 201, role.text
        managed_user = client.post(
            "/api/v1/auth/users",
            headers=auth,
            json={
                "email": "viewer@example.test",
                "display_name": "Operations Viewer",
                "password": "Secure-Viewer1!",
                "role_ids": [role.json()["id"]],
            },
        )
        assert managed_user.status_code == 201, managed_user.text
        assert managed_user.json()["roles"] == ["operations_viewer"]
        users = client.get("/api/v1/auth/users", headers=auth)
        roles = client.get("/api/v1/auth/roles", headers=auth)
        assert users.status_code == roles.status_code == 200
        assert len(users.json()) == 2
        assert len(roles.json()) == 2
        updated_user = client.patch(
            f"/api/v1/auth/users/{managed_user.json()['id']}",
            headers=auth,
            json={"display_name": "Updated Operations Viewer"},
        )
        assert updated_user.status_code == 200, updated_user.text
        updated_role = client.patch(
            f"/api/v1/auth/roles/{role.json()['id']}",
            headers=auth,
            json={"description": "Updated read-only operations role"},
        )
        assert updated_role.status_code == 200, updated_role.text
        viewer_login = client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": "api-integration",
                "email": "viewer@example.test",
                "password": "Secure-Viewer1!",
            },
        )
        assert viewer_login.status_code == 200, viewer_login.text
        viewer_auth = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
        assert client.get("/api/v1/assets", headers=viewer_auth).status_code == 200
        forbidden_create = client.post(
            "/api/v1/projects",
            headers=viewer_auth,
            json={"name": "Must Not Exist", "slug": "must-not-exist"},
        )
        assert forbidden_create.status_code == 403

        integration = client.post(
            "/api/v1/integrations",
            headers=auth,
            json={
                "project_id": project_id,
                "slug": "integration-prometheus",
                "name": "Integration Prometheus",
                "integration_type": "prometheus",
                "endpoint": "http://prometheus:9090",
                "credential_ref": "vault://kv/integration/prometheus",
                "enabled": False,
                "capabilities": ["metrics.read"],
                "configuration": {"query_timeout_seconds": 5},
            },
        )
        assert integration.status_code == 201, integration.text
        assert integration.json()["credential_configured"] is True
        assert "credential_ref" not in integration.text
        disabled_probe = client.post(
            f"/api/v1/integrations/{integration.json()['id']}/probe", headers=auth
        )
        assert disabled_probe.status_code == 200, disabled_probe.text
        assert disabled_probe.json()["health_status"] == "disabled"
        integration_id = integration.json()["id"]
        assert client.get(f"/api/v1/integrations/{integration_id}", headers=auth).status_code == 200
        enabled_integration = client.patch(
            f"/api/v1/integrations/{integration_id}",
            headers=auth,
            json={"enabled": True, "name": "Integration Prometheus Updated"},
        )
        assert enabled_integration.status_code == 200, enabled_integration.text
        assert enabled_integration.json()["config_version"] == 2
        disabled_again = client.patch(
            f"/api/v1/integrations/{integration_id}", headers=auth, json={"enabled": False}
        )
        assert disabled_again.status_code == 200, disabled_again.text

        starts_at = datetime.now(UTC) + timedelta(hours=1)
        ends_at = starts_at + timedelta(hours=2)
        maintenance = client.post(
            "/api/v1/maintenance-windows",
            headers=auth,
            json={
                "project_id": project_id,
                "asset_id": asset_id,
                "name": "Integration maintenance",
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
            },
        )
        assert maintenance.status_code == 201, maintenance.text
        disabled_window = client.patch(
            f"/api/v1/maintenance-windows/{maintenance.json()['id']}",
            headers=auth,
            json={"enabled": False},
        )
        assert disabled_window.status_code == 200, disabled_window.text
        assert disabled_window.json()["enabled"] is False
        windows = client.get("/api/v1/maintenance-windows", headers=auth)
        assert windows.status_code == 200
        assert windows.json()["total"] == 1

        registration = client.post(
            "/api/v1/agents/registration-tokens",
            headers=auth,
            json={"project_id": project_id, "asset_id": asset_id, "expires_in_seconds": 300},
        )
        assert registration.status_code == 201, registration.text
        registration_token = registration.json()["token"]
        assert registration_token.startswith("axt_")

        agent_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-agent")]))
            .sign(agent_key, hashes.SHA256())
        )
        enrollment_payload = {
            "registration_token": registration_token,
            "name": "Integration Agent",
            "hostname": "integration-host",
            "platform": "linux",
            "architecture": "amd64",
            "version": "test",
            "csr_pem": csr.public_bytes(serialization.Encoding.PEM).decode(),
            "capabilities": {"actions": ["system.disk_usage"]},
        }
        enrollment = client.post("/api/v1/agents/enroll", json=enrollment_payload)
        assert enrollment.status_code == 201, enrollment.text
        enrolled = enrollment.json()
        agent_id = enrolled["agent_id"]
        agent_certificate = x509.load_pem_x509_certificate(enrolled["certificate_pem"].encode())
        agent_headers = {
            "X-SSL-Client-Verify": "SUCCESS",
            # Nginx can retain the ASN.1 INTEGER sign-padding byte even though
            # cryptography and the database represent the serial as an integer.
            "X-SSL-Client-Serial": f"00{agent_certificate.serial_number:x}",
            "X-SSL-Client-Cert": quote(enrolled["certificate_pem"], safe=""),
        }

        replay = client.post("/api/v1/agents/enroll", json=enrollment_payload)
        assert replay.status_code == 401

        heartbeat = client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=agent_headers,
            json={
                "hostname": "integration-host",
                "platform": "linux",
                "architecture": "amd64",
                "version": "test",
                "health_status": "healthy",
                "capabilities": {"actions": ["system.disk_usage"]},
            },
        )
        assert heartbeat.status_code == 200, heartbeat.text
        assert heartbeat.json()["status"] == "online"

        renewal_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        renewal_csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-agent-renewal")])
            )
            .sign(renewal_key, hashes.SHA256())
        )
        renewal_payload = {"csr_pem": renewal_csr.public_bytes(serialization.Encoding.PEM).decode()}
        too_early = client.post(
            f"/api/v1/agents/{agent_id}/certificate/renew",
            headers=agent_headers,
            json=renewal_payload,
        )
        assert too_early.status_code == 409, too_early.text

        async with factory() as certificate_session:
            async with certificate_session.begin():
                expiring_agent = await certificate_session.scalar(
                    select(EdgeAgent).where(EdgeAgent.id == UUID(agent_id))
                )
                assert expiring_agent is not None
                expiring_agent.certificate_not_after = datetime.now(UTC) + timedelta(hours=1)

        renewal = client.post(
            f"/api/v1/agents/{agent_id}/certificate/renew",
            headers=agent_headers,
            json=renewal_payload,
        )
        assert renewal.status_code == 200, renewal.text
        assert renewal.json()["agent_id"] == agent_id
        renewed_certificate = x509.load_pem_x509_certificate(
            renewal.json()["certificate_pem"].encode()
        )
        renewed_headers = {
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-Serial": format(renewed_certificate.serial_number, "x"),
            "X-SSL-Client-Cert": quote(renewal.json()["certificate_pem"], safe=""),
        }

        renewed_heartbeat = client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=renewed_headers,
            json={
                "hostname": "integration-host",
                "platform": "linux",
                "architecture": "amd64",
                "version": "test",
                "health_status": "healthy",
                "capabilities": {"actions": ["system.disk_usage"]},
            },
        )
        assert renewed_heartbeat.status_code == 200, renewed_heartbeat.text

        overlap_heartbeat = client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=agent_headers,
            json={
                "hostname": "integration-host",
                "platform": "linux",
                "architecture": "amd64",
                "version": "test",
                "health_status": "healthy",
                "capabilities": {"actions": ["system.disk_usage"]},
            },
        )
        assert overlap_heartbeat.status_code == 401, overlap_heartbeat.text

        mismatched_retry_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        mismatched_retry_csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mismatched-retry")]))
            .sign(mismatched_retry_key, hashes.SHA256())
        )
        mismatched_retry = client.post(
            f"/api/v1/agents/{agent_id}/certificate/renew",
            headers=agent_headers,
            json={
                "csr_pem": mismatched_retry_csr.public_bytes(serialization.Encoding.PEM).decode()
            },
        )
        assert mismatched_retry.status_code == 409, mismatched_retry.text

        retry_renewal = client.post(
            f"/api/v1/agents/{agent_id}/certificate/renew",
            headers=agent_headers,
            json=renewal_payload,
        )
        assert retry_renewal.status_code == 200, retry_renewal.text
        retry_certificate = x509.load_pem_x509_certificate(
            retry_renewal.json()["certificate_pem"].encode()
        )
        agent_headers = {
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-Serial": format(retry_certificate.serial_number, "x"),
            "X-SSL-Client-Cert": quote(retry_renewal.json()["certificate_pem"], safe=""),
        }
        assert (
            client.post(
                f"/api/v1/agents/{agent_id}/certificate/renew",
                headers=agent_headers,
                json=renewal_payload,
            ).status_code
            == 409
        )
        agent_list = client.get("/api/v1/agents", headers=auth)
        assert agent_list.status_code == 200
        assert agent_list.json()["total"] == 1

        task = client.post(
            f"/api/v1/agents/{agent_id}/tasks",
            headers={**auth, "Idempotency-Key": "disk-integration-task-1"},
            json={"action_id": "system.disk_usage", "parameters": {"paths": ["/"]}},
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["id"]
        dispatched = client.get(f"/api/v1/agents/{agent_id}/tasks/next", headers=agent_headers)
        assert dispatched.status_code == 200, dispatched.text
        assert dispatched.json()["task_id"] == task_id
        assert dispatched.json()["signature"]

        result = client.post(
            f"/api/v1/agents/{agent_id}/tasks/{task_id}/result",
            headers=agent_headers,
            json={
                "status": "succeeded",
                "duration_ms": 12,
                "sanitized_output": {"filesystems": [{"path": "/", "total_bytes": 1024}]},
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "succeeded"
        task_list = client.get(f"/api/v1/agents/{agent_id}/tasks", headers=auth)
        assert task_list.status_code == 200
        assert task_list.json()["total"] == 1

        monitor_target = client.post(
            "/api/v1/monitoring/targets",
            headers=auth,
            json={
                "project_id": project_id,
                "asset_id": asset_id,
                "name": "Integration host node exporter",
                "prometheus_job": "node",
                "prometheus_instance": "integration-host:9100",
            },
        )
        assert monitor_target.status_code == 201, monitor_target.text
        target_verification = client.post(
            f"/api/v1/monitoring/targets/{monitor_target.json()['id']}/verify",
            headers=auth,
        )
        assert target_verification.status_code == 200, target_verification.text

        alert_webhook = client.post(
            "/api/v1/webhooks/alertmanager",
            headers={"Authorization": "Bearer change-me-development-alertmanager-token"},
            json={
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "AutomationIntegrationTest",
                            "severity": "warning",
                            "service": "node-observability",
                            "job": "node",
                            "instance": "integration-host:9100",
                            "aiops_tenant_slug": "api-integration",
                            "aiops_project_slug": "authorized-test",
                            "aiops_asset_id": "TEST-LINUX-001",
                        },
                        "annotations": {
                            "summary": "Automation integration event",
                            "evidence_query": 'up{job="node"}',
                        },
                        "startsAt": "2026-08-12T07:00:00Z",
                        "endsAt": "0001-01-01T00:00:00Z",
                        "fingerprint": "automation-integration-source",
                    }
                ],
            },
        )
        assert alert_webhook.status_code == 200, alert_webhook.text
        event_id = client.get("/api/v1/events", headers=auth).json()["items"][0]["id"]

        runbook_response = client.post(
            "/api/v1/runbooks/builtins",
            headers=auth,
            json={"project_id": project_id},
        )
        assert runbook_response.status_code == 201, runbook_response.text
        runbook = runbook_response.json()
        assert runbook["versions"][0]["risk_level"] == "R0"
        assert runbook["versions"][0]["input_schema"]["additionalProperties"] is False
        immutable_version_id = runbook["versions"][0]["id"]
        existing_runbook = client.post(
            "/api/v1/runbooks/builtins", headers=auth, json={"project_id": project_id}
        )
        assert existing_runbook.status_code == 201, existing_runbook.text
        runbook_list = client.get(f"/api/v1/runbooks?project_id={project_id}", headers=auth)
        assert runbook_list.status_code == 200
        assert runbook_list.json()["total"] == 1
        assert client.get(f"/api/v1/runbooks/{runbook['id']}", headers=auth).status_code == 200

        automation_job = client.post(
            "/api/v1/automation/jobs",
            headers={**auth, "Idempotency-Key": "automation-integration-job-1"},
            json={
                "runbook_id": runbook["id"],
                "runbook_version": 1,
                "asset_id": asset_id,
                "event_id": event_id,
                "inputs": {"paths": ["/"]},
            },
        )
        assert automation_job.status_code == 201, automation_job.text
        job = automation_job.json()
        assert job["status"] == "queued"
        assert job["approval_status"] == "not_required"
        assert job["runbook_version_id"] == immutable_version_id
        assert job["policy_snapshot"]["permission_verified"] is True

        automation_task = client.get(f"/api/v1/agents/{agent_id}/tasks/next", headers=agent_headers)
        assert automation_task.status_code == 200, automation_task.text
        automation_task_id = automation_task.json()["task_id"]
        running_job = client.get(f"/api/v1/automation/jobs/{job['id']}", headers=auth).json()
        assert running_job["status"] == "running"
        assert running_job["started_at"] is not None
        automation_result = client.post(
            f"/api/v1/agents/{agent_id}/tasks/{automation_task_id}/result",
            headers=agent_headers,
            json={
                "status": "succeeded",
                "duration_ms": 18,
                "sanitized_output": {
                    "filesystems": [{"path": "/", "total_bytes": 2048, "available_bytes": 1024}]
                },
            },
        )
        assert automation_result.status_code == 200, automation_result.text
        completed_job = client.get(f"/api/v1/automation/jobs/{job['id']}", headers=auth).json()
        assert completed_job["status"] == "succeeded"
        assert completed_job["duration_ms"] == 18
        jobs = client.get("/api/v1/automation/jobs", headers=auth)
        assert jobs.status_code == 200
        assert jobs.json()["total"] == 1
        approvals = client.get("/api/v1/approvals", headers=auth)
        assert approvals.status_code == 200
        assert approvals.json()["total"] == 0
        event_detail = client.get(f"/api/v1/events/{event_id}", headers=auth).json()
        assert event_detail["automation_jobs"][0]["status"] == "succeeded"
        assert any(
            item["category"] == "automation" and item["title"] == "Runbook 执行成功"
            for item in event_detail["timeline"]
        )

        ai_summary = client.post(f"/api/v1/ai/events/{event_id}/summary", headers=auth)
        assert ai_summary.status_code == 200, ai_summary.text
        assert ai_summary.json()["status"] == "not_configured"
        assert ai_summary.json()["summary"] == "AI 服务未配置"

        system_info = client.get("/api/v1/system/info", headers=auth)
        assert system_info.status_code == 200, system_info.text
        assert system_info.json()["service"] == "aiops-x-api"

        assets = client.get("/api/v1/assets", headers=auth)
        assert assets.status_code == 200
        assert assets.json()["total"] == 2
        assert {item["asset_id"] for item in assets.json()["items"]} == {
            "TEST-LINUX-001",
            "TEST-APP-001",
        }

        audits = client.get("/api/v1/audit-logs?page_size=100", headers=auth)
        assert audits.status_code == 200
        actions = {item["action"] for item in audits.json()["items"]}
        assert {
            "identity.bootstrap.completed",
            "identity.login.succeeded",
            "project.created",
            "asset.created",
            "asset.relation.created",
            "asset.relation.expired",
            "identity.role.created",
            "identity.user.created",
            "integration.created",
            "integration.probed",
            "maintenance_window.created",
            "maintenance_window.updated",
            "agent.registration_token.created",
            "agent.registered",
            "agent.heartbeat.received",
            "agent.certificate.renewed",
            "agent.task.queued",
            "agent.task.dispatched",
            "agent.task.completed",
            "runbook.published",
            "automation.job.requested",
            "automation.job.completed",
            "ai.analysis.skipped",
        } <= actions
        async with factory() as verification_session:
            outbox_count = await verification_session.scalar(
                select(func.count()).select_from(EventOutbox)
            )
            outbox_event = await verification_session.scalar(
                select(EventOutbox).where(EventOutbox.event_type == "automation.job.completed")
            )
        assert (outbox_count or 0) >= len(actions)
        assert outbox_event is not None
        assert outbox_event.payload["event_version"] == 1
        assert outbox_event.payload["tenant_id"] == outbox_event.payload["data"].get(
            "tenant_id", outbox_event.payload["tenant_id"]
        )
        assert outbox_event.payload["tenant_id"] == tokens["user"]["tenant_id"]

        assert admin_refresh_cookie is not None
        client.cookies.set("aiops_x_refresh", admin_refresh_cookie, path="/api/v1/auth")
        refreshed = client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": tokens["csrf_token"]},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["access_token"] != access_token
        rotated_refresh_cookie = refreshed.cookies.get("aiops_x_refresh")
        assert rotated_refresh_cookie is not None
        client.cookies.clear()
        client.cookies.set("aiops_x_refresh", rotated_refresh_cookie, path="/api/v1/auth")

        logout = client.post(
            "/api/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {refreshed.json()['access_token']}",
                "X-CSRF-Token": refreshed.json()["csrf_token"],
            },
        )
        assert logout.status_code == 204

        client.cookies.clear()
        replay_client = TestClient(app)
        replay_client.cookies.set("aiops_x_refresh", admin_refresh_cookie, path="/api/v1/auth")
        replayed = replay_client.post(
            "/api/v1/auth/refresh", headers={"X-CSRF-Token": tokens["csrf_token"]}
        )
        assert replayed.status_code == 401

    app.dependency_overrides.clear()
    await engine.dispose()
    get_settings.cache_clear()


def _configure_test_agent_pki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Agent CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    task_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    task_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Task Signing")])
    task_certificate = (
        x509.CertificateBuilder()
        .subject_name(task_name)
        .issuer_name(task_name)
        .public_key(task_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .sign(task_key, hashes.SHA256())
    )

    paths = {
        "AIOPS_AGENT_CA_KEY_PATH": (tmp_path / "ca-key.pem", _private_pem(ca_key)),
        "AIOPS_AGENT_CA_CERTIFICATE_PATH": (
            tmp_path / "ca-cert.pem",
            ca_certificate.public_bytes(serialization.Encoding.PEM),
        ),
        "AIOPS_AGENT_TASK_SIGNING_KEY_PATH": (
            tmp_path / "task-key.pem",
            _private_pem(task_key),
        ),
        "AIOPS_AGENT_TASK_SIGNING_CERTIFICATE_PATH": (
            tmp_path / "task-cert.pem",
            task_certificate.public_bytes(serialization.Encoding.PEM),
        ),
    }
    for environment_name, (path, content) in paths.items():
        path.write_bytes(content)
        monkeypatch.setenv(environment_name, str(path))
    get_settings.cache_clear()


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
