#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from live_common import AcceptanceError, ApiClient, require_secret_environment, write_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run M1 identity, tenant, RBAC, and CMDB acceptance against a live deployment."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-health-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-slug", default=os.getenv("AIOPS_ACCEPTANCE_TENANT_SLUG", ""))
    parser.add_argument("--admin-email", default=os.getenv("AIOPS_ACCEPTANCE_ADMIN_EMAIL", ""))
    parser.add_argument("--evidence-file", type=Path, required=True)
    return parser.parse_args()


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} response was not an object")
    return value


def main() -> int:
    args = parse_args()
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    tenant_slug = args.tenant_slug.strip().lower()
    admin_email = args.admin_email.strip().lower()
    if not tenant_slug or not admin_email:
        raise AcceptanceError("tenant slug and admin email are required")

    health_client = ApiClient(args.api_health_url)
    require_mapping(health_client.request("GET", "/health").body, "API health")
    require_mapping(health_client.request("GET", "/ready").body, "API readiness")
    client = ApiClient(args.base_url)
    started_at = datetime.now(UTC)
    run_id = started_at.strftime("%Y%m%dt%H%M%Sz").lower() + secrets.token_hex(2)
    request_ids: list[str] = []

    bootstrap_status = client.request("GET", "/api/v1/auth/bootstrap/status")
    bootstrap = require_mapping(bootstrap_status.body, "bootstrap status")
    bootstrapped = False
    if bootstrap.get("required") is True:
        bootstrap_token = require_secret_environment("AIOPS_ACCEPTANCE_BOOTSTRAP_TOKEN")
        created = client.request(
            "POST",
            "/api/v1/auth/bootstrap",
            headers={"X-Bootstrap-Token": bootstrap_token},
            payload={
                "tenant_name": "AIOps-X M1 Acceptance",
                "tenant_slug": tenant_slug,
                "email": admin_email,
                "display_name": "M1 Acceptance Admin",
                "password": admin_password,
            },
            expected={201},
        )
        if created.request_id:
            request_ids.append(created.request_id)
        bootstrapped = True

    user = client.login(tenant_slug, admin_email, admin_password)
    if "platform_admin" not in user.get("roles", []):
        raise AcceptanceError("acceptance account is not a platform administrator")
    me = require_mapping(client.request("GET", "/api/v1/auth/me").body, "current user")
    if "platform_admin" not in me.get("roles", []):
        raise AcceptanceError("/auth/me did not confirm the platform administrator role")

    project_response = client.request(
        "POST",
        "/api/v1/projects",
        headers={"Idempotency-Key": f"m1-live-project-{run_id}"},
        payload={"name": f"M1 Live {run_id}", "slug": f"m1-live-{run_id}"},
        expected={201},
    )
    if project_response.request_id:
        request_ids.append(project_response.request_id)
    project = require_mapping(project_response.body, "project")
    project_id = str(project["id"])
    client.request(
        "POST",
        "/api/v1/projects",
        headers={"Idempotency-Key": f"m1-live-project-{run_id}"},
        payload={"name": f"M1 Live {run_id}", "slug": f"m1-live-{run_id}"},
        expected={409},
    )
    projects = require_mapping(
        client.request("GET", f"/api/v1/projects?search={run_id}&page_size=100").body,
        "project search",
    )
    if projects.get("total") != 1:
        raise AcceptanceError("repeated project request did not leave exactly one project")
    project_update = require_mapping(
        client.request(
            "PATCH",
            f"/api/v1/projects/{project_id}",
            payload={"name": f"M1 Live Verified {run_id}"},
        ).body,
        "project update",
    )
    if "Verified" not in str(project_update.get("name")):
        raise AcceptanceError("project update was not persisted")

    host = require_mapping(
        client.request(
            "POST",
            "/api/v1/assets",
            headers={"Idempotency-Key": f"m1-live-host-{run_id}"},
            payload={
                "asset_id": f"M1-LIVE-HOST-{run_id.upper()}",
                "project_id": project_id,
                "asset_type": "linux",
                "name": f"M1 Live Linux {run_id}",
                "hostname": f"m1-live-{run_id}",
                "ip_addresses": ["192.0.2.11"],
                "environment": "test",
                "criticality": "low",
                "gxp_classification": "unclassified",
                "credential_ref": f"vault://kv/acceptance/{run_id}/host",
                "tags": ["acceptance", "m1"],
            },
            expected={201},
        ).body,
        "host asset",
    )
    if host.get("credential_configured") is not True or "credential_ref" in host:
        raise AcceptanceError("asset credential reference was not safely redacted")
    host_id = str(host["id"])
    updated_host = require_mapping(
        client.request(
            "PATCH",
            f"/api/v1/assets/{host_id}",
            payload={"operating_system": "Linux acceptance", "location": "test-environment"},
        ).body,
        "host asset update",
    )
    if updated_host.get("location") != "test-environment":
        raise AcceptanceError("host asset update was not persisted")

    application = require_mapping(
        client.request(
            "POST",
            "/api/v1/assets",
            headers={"Idempotency-Key": f"m1-live-app-{run_id}"},
            payload={
                "asset_id": f"M1-LIVE-APP-{run_id.upper()}",
                "project_id": project_id,
                "asset_type": "application",
                "name": f"M1 Live Application {run_id}",
                "environment": "test",
                "tags": ["acceptance", "m1"],
            },
            expected={201},
        ).body,
        "application asset",
    )
    application_id = str(application["id"])
    relation = require_mapping(
        client.request(
            "POST",
            f"/api/v1/assets/{application_id}/relations",
            payload={
                "target_asset_id": host_id,
                "relation_type": "RUNS_ON",
                "source": "m1-live-acceptance",
                "confidence": "high",
                "manually_confirmed": True,
            },
            expected={201},
        ).body,
        "asset relation",
    )
    relation_id = str(relation["id"])
    incoming = require_mapping(
        client.request("GET", f"/api/v1/assets/{host_id}/relations?direction=incoming").body,
        "incoming relations",
    )
    if not any(str(item.get("id")) == relation_id for item in incoming.get("items", [])):
        raise AcceptanceError("RUNS_ON relation was not returned by incoming query")
    client.request(
        "DELETE",
        f"/api/v1/assets/{application_id}/relations/{relation_id}",
        expected={204},
    )
    active_relations = require_mapping(
        client.request("GET", f"/api/v1/assets/{host_id}/relations?direction=incoming").body,
        "active relations after expiry",
    )
    if any(str(item.get("id")) == relation_id for item in active_relations.get("items", [])):
        raise AcceptanceError("expired relation remained visible in the active relation list")
    historical_relations = require_mapping(
        client.request(
            "GET",
            f"/api/v1/assets/{host_id}/relations?direction=incoming&active_only=false",
        ).body,
        "historical relations after expiry",
    )
    if not any(
        str(item.get("id")) == relation_id for item in historical_relations.get("items", [])
    ):
        raise AcceptanceError("expired relation was not retained in relation history")

    role = require_mapping(
        client.request(
            "POST",
            "/api/v1/auth/roles",
            payload={
                "name": f"m1_viewer_{run_id}",
                "description": "M1 live read-only acceptance role",
                "permissions": ["project:read", "asset:read"],
            },
            expected={201},
        ).body,
        "read-only role",
    )
    viewer_password = "M1!a" + secrets.token_urlsafe(18)
    viewer_email = f"m1-viewer-{run_id}@example.test"
    viewer = require_mapping(
        client.request(
            "POST",
            "/api/v1/auth/users",
            payload={
                "email": viewer_email,
                "display_name": f"M1 Viewer {run_id}",
                "password": viewer_password,
                "role_ids": [role["id"]],
            },
            expected={201},
        ).body,
        "read-only user",
    )

    viewer_client = ApiClient(args.base_url)
    viewer_client.login(tenant_slug, viewer_email, viewer_password)
    viewer_client.request("GET", "/api/v1/assets")
    forbidden = viewer_client.request(
        "POST",
        "/api/v1/projects",
        payload={"name": "M1 Forbidden Project", "slug": f"m1-forbidden-{run_id}"},
        expected={403},
    )
    if forbidden.request_id:
        request_ids.append(forbidden.request_id)

    audit_response = client.request("GET", "/api/v1/audit-logs?page_size=100")
    if audit_response.request_id:
        request_ids.append(audit_response.request_id)
    audits = require_mapping(audit_response.body, "audit logs")
    audit_actions = {str(item.get("action")) for item in audits.get("items", [])}
    required_actions = {
        "identity.login.succeeded",
        "project.created",
        "project.updated",
        "asset.created",
        "asset.updated",
        "asset.relation.created",
        "asset.relation.expired",
        "identity.role.created",
        "identity.user.created",
    }
    if bootstrapped:
        required_actions.add("identity.bootstrap.completed")
    missing_actions = sorted(required_actions - audit_actions)
    if missing_actions:
        raise AcceptanceError(f"M1 audit actions are missing: {missing_actions}")

    evidence = {
        "milestone": "M1",
        "status": "restart_required",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "base_url": client.base_url.rstrip("/"),
        "api_health_url": health_client.base_url.rstrip("/"),
        "tenant_slug": tenant_slug,
        "admin_email": admin_email,
        "bootstrap_performed": bootstrapped,
        "project_id": project_id,
        "host_asset_id": host_id,
        "application_asset_id": application_id,
        "relation_id": relation_id,
        "relation_expired": True,
        "viewer_user_id": str(viewer["id"]),
        "viewer_forbidden_status": forbidden.status,
        "credential_reference_redacted": True,
        "audit_actions_verified": sorted(required_actions),
        "request_ids": request_ids,
        "secrets_recorded": False,
    }
    write_evidence(args.evidence_file, evidence)
    print(f"M1 live CRUD/RBAC gate passed; restart verification required: {args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"M1 live acceptance failed: {error}")
        raise SystemExit(1) from None
