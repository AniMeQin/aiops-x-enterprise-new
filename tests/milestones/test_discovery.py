from typing import Any

import pytest
from aiops_x_api.modules.discovery.api import get_discovery_backend
from aiops_x_api.modules.discovery.ports import DiscoveryObservation


class RecordedDiscoveryBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.observations = [DiscoveryObservation(ip_address="10.20.30.40", open_ports=(22, 9100))]

    async def discover(
        self,
        *,
        networks: tuple[str, ...],
        ports: tuple[int, ...],
        timeout_seconds: float,
        max_hosts: int,
    ) -> list[DiscoveryObservation]:
        self.calls.append(
            {
                "networks": networks,
                "ports": ports,
                "timeout_seconds": timeout_seconds,
                "max_hosts": max_hosts,
            }
        )
        return self.observations


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_discovery_candidate_requires_confirmation_before_cmdb(
    milestone_context: Any,
) -> None:
    client = milestone_context.client
    backend = RecordedDiscoveryBackend()
    client.app.dependency_overrides[get_discovery_backend] = lambda: backend
    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
        json={
            "tenant_name": "Discovery Acceptance Tenant",
            "tenant_slug": "discovery-acceptance",
            "email": "admin@discovery.example.test",
            "display_name": "Discovery Admin",
            "password": "Discovery-Admin1!",
        },
    )
    assert bootstrap.status_code == 201, bootstrap.text
    login = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "discovery-acceptance",
            "email": "admin@discovery.example.test",
            "password": "Discovery-Admin1!",
        },
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    project = client.post(
        "/api/v1/projects",
        headers=auth,
        json={"name": "Discovery Acceptance", "slug": "discovery-acceptance"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    public_network = client.post(
        "/api/v1/discovery/jobs",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "forbidden-public-scan",
            "networks": ["203.0.113.0/30"],
            "ports": [22],
        },
    )
    assert public_network.status_code == 422
    assert public_network.json()["code"] == "AIOPS_3301"

    scheduled = client.post(
        "/api/v1/discovery/jobs",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "scheduled-private-subnet",
            "networks": ["10.20.30.41/32"],
            "ports": [22],
            "schedule_enabled": True,
            "schedule_interval_seconds": 300,
        },
    )
    assert scheduled.status_code == 201, scheduled.text
    assert scheduled.json()["schedule_enabled"] is True
    assert scheduled.json()["next_run_at"] is not None

    job = client.post(
        "/api/v1/discovery/jobs",
        headers=auth,
        json={
            "project_id": project_id,
            "name": "private-subnet-tcp",
            "networks": ["10.20.30.40/32"],
            "ports": [9100, 22],
            "timeout_seconds": 0.25,
            "max_hosts": 1,
        },
    )
    assert job.status_code == 201, job.text
    run = client.post(f"/api/v1/discovery/jobs/{job.json()['id']}/run", headers=auth)
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "succeeded"
    assert run.json()["observed_host_count"] == 1
    assert backend.calls == [
        {
            "networks": ("10.20.30.40/32",),
            "ports": (22, 9100),
            "timeout_seconds": 0.25,
            "max_hosts": 1,
        }
    ]

    assets_before = client.get("/api/v1/assets", headers=auth)
    assert assets_before.json()["total"] == 0
    candidates = client.get(
        f"/api/v1/discovery/candidates?project_id={project_id}&status=pending",
        headers=auth,
    )
    assert candidates.status_code == 200, candidates.text
    candidate = candidates.json()["items"][0]
    assert candidate["ip_address"] == "10.20.30.40"
    assert candidate["observed_ports"] == [22, 9100]
    assert candidate["evidence"]["method"] == "tcp_connect"
    assert candidate["match_status"] == "none"

    confirmation = client.post(
        f"/api/v1/discovery/candidates/{candidate['id']}/confirm",
        headers=auth,
        json={
            "asset_id": "DISC-LINUX-001",
            "asset_type": "linux",
            "name": "Discovered Linux Host",
            "environment": "test",
            "criticality": "medium",
            "gxp_classification": "non_gxp",
            "tags": ["discovered"],
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    asset = client.get(f"/api/v1/assets/{confirmation.json()['asset_id']}", headers=auth)
    assert asset.status_code == 200, asset.text
    assert asset.json()["ip_addresses"] == ["10.20.30.40"]
    assert asset.json()["monitoring_status"] == "not_configured"
    assert asset.json()["discovery_source"] == "controlled_tcp"
    assert asset.json()["discovery_status"] == "confirmed"
    assert "credential_ref" not in asset.text

    database = client.post(
        f"/api/v1/assets/{confirmation.json()['asset_id']}/components",
        headers=auth,
        json={
            "component_type": "database_instance",
            "external_id": "postgres:5432/app",
            "name": "Application PostgreSQL",
            "status": "observed",
            "source": "controlled-discovery-test",
            "attributes": {"engine": "postgresql", "port": 5432},
            "observed_at": candidate["last_seen_at"],
        },
    )
    assert database.status_code == 201, database.text
    container = client.post(
        f"/api/v1/assets/{confirmation.json()['asset_id']}/components",
        headers=auth,
        json={
            "parent_component_id": database.json()["id"],
            "component_type": "container",
            "external_id": "sha256:acceptance",
            "name": "postgres-container",
            "status": "running",
            "source": "controlled-discovery-test",
            "attributes": {"runtime": "docker"},
            "observed_at": candidate["last_seen_at"],
        },
    )
    assert container.status_code == 201, container.text
    components = client.get(
        f"/api/v1/assets/{confirmation.json()['asset_id']}/components", headers=auth
    )
    assert components.status_code == 200
    assert components.json()["total"] == 2

    backend.observations = []
    second_run = client.post(f"/api/v1/discovery/jobs/{job.json()['id']}/run", headers=auth)
    assert second_run.status_code == 201
    confirmed = client.get(
        f"/api/v1/discovery/candidates?project_id={project_id}&status=confirmed",
        headers=auth,
    )
    assert confirmed.json()["total"] == 1

    audits = client.get("/api/v1/audit-logs?page_size=100", headers=auth)
    actions = {item["action"] for item in audits.json()["items"]}
    assert {
        "discovery.job.created",
        "discovery.run.completed",
        "discovery.candidate.confirmed",
    } <= actions
