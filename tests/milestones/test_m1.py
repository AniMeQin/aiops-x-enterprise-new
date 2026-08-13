from typing import Any

import pytest


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_m1_identity_tenant_and_cmdb_acceptance(milestone_context: Any) -> None:
    client = milestone_context.client
    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
        json={
            "tenant_name": "M1 Acceptance Tenant",
            "tenant_slug": "m1-acceptance",
            "email": "admin@m1.example.test",
            "display_name": "M1 Admin",
            "password": "M1-Secure-Admin1!",
        },
    )
    assert bootstrap.status_code == 201, bootstrap.text

    login = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "m1-acceptance",
            "email": "admin@m1.example.test",
            "password": "M1-Secure-Admin1!",
        },
    )
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=auth).json()["roles"] == ["platform_admin"]

    project = client.post(
        "/api/v1/projects",
        headers={**auth, "Idempotency-Key": "m1-acceptance-project"},
        json={"name": "M1 Acceptance", "slug": "m1-acceptance-project"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    host = client.post(
        "/api/v1/assets",
        headers={**auth, "Idempotency-Key": "m1-acceptance-host"},
        json={
            "asset_id": "M1-LINUX-001",
            "project_id": project_id,
            "asset_type": "linux",
            "name": "M1 Linux Host",
            "hostname": "m1-linux-001",
            "ip_addresses": ["192.0.2.11"],
            "environment": "test",
            "credential_ref": "vault://kv/m1/linux-001",
        },
    )
    assert host.status_code == 201, host.text
    assert host.json()["credential_configured"] is True
    assert "credential_ref" not in host.text

    application = client.post(
        "/api/v1/assets",
        headers={**auth, "Idempotency-Key": "m1-acceptance-app"},
        json={
            "asset_id": "M1-APP-001",
            "project_id": project_id,
            "asset_type": "application",
            "name": "M1 Application",
            "environment": "test",
        },
    )
    assert application.status_code == 201, application.text
    relation = client.post(
        f"/api/v1/assets/{application.json()['id']}/relations",
        headers=auth,
        json={
            "target_asset_id": host.json()["id"],
            "relation_type": "RUNS_ON",
            "source": "m1-acceptance",
            "confidence": "high",
            "manually_confirmed": True,
        },
    )
    assert relation.status_code == 201, relation.text
    incoming = client.get(
        f"/api/v1/assets/{host.json()['id']}/relations?direction=incoming",
        headers=auth,
    )
    assert incoming.status_code == 200, incoming.text
    assert incoming.json()["items"][0]["relation_type"] == "RUNS_ON"

    role = client.post(
        "/api/v1/auth/roles",
        headers=auth,
        json={
            "name": "m1_viewer",
            "description": "M1 read-only role",
            "permissions": ["project:read", "asset:read"],
        },
    )
    assert role.status_code == 201, role.text
    viewer = client.post(
        "/api/v1/auth/users",
        headers=auth,
        json={
            "email": "viewer@m1.example.test",
            "display_name": "M1 Viewer",
            "password": "M1-Secure-Viewer1!",
            "role_ids": [role.json()["id"]],
        },
    )
    assert viewer.status_code == 201, viewer.text
    viewer_login = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "m1-acceptance",
            "email": "viewer@m1.example.test",
            "password": "M1-Secure-Viewer1!",
        },
    )
    viewer_auth = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
    assert client.get("/api/v1/assets", headers=viewer_auth).status_code == 200
    assert (
        client.post(
            "/api/v1/projects",
            headers=viewer_auth,
            json={"name": "Forbidden", "slug": "forbidden"},
        ).status_code
        == 403
    )

    audits = client.get("/api/v1/audit-logs?page_size=100", headers=auth)
    assert audits.status_code == 200, audits.text
    actions = {item["action"] for item in audits.json()["items"]}
    assert {
        "identity.bootstrap.completed",
        "identity.login.succeeded",
        "project.created",
        "asset.created",
        "asset.relation.created",
        "identity.role.created",
        "identity.user.created",
    } <= actions
