#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from live_common import AcceptanceError, ApiClient, require_secret_environment, write_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify M1 resources after an API/Web restart and issue passed evidence."
    )
    parser.add_argument("--prepared-evidence", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    return parser.parse_args()


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} response was not an object")
    return value


def load_prepared_evidence(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read prepared M1 evidence: {error}") from error
    if not isinstance(document, dict) or document.get("status") != "restart_required":
        raise AcceptanceError("prepared M1 evidence does not require restart verification")
    required_fields = {
        "base_url",
        "api_health_url",
        "tenant_slug",
        "admin_email",
        "project_id",
        "host_asset_id",
        "application_asset_id",
        "relation_id",
        "audit_actions_verified",
    }
    missing = sorted(field for field in required_fields if not document.get(field))
    if missing:
        raise AcceptanceError(f"prepared M1 evidence is missing fields: {missing}")
    return document


def find_missing_audit_actions(client: ApiClient, required_actions: set[str]) -> list[str]:
    available_actions: set[str] = set()
    for action in sorted(required_actions):
        audits = require_mapping(
            client.request(
                "GET",
                f"/api/v1/audit-logs?page_size=1&action={quote(action, safe='')}",
            ).body,
            f"audit logs for {action} after restart",
        )
        if any(str(item.get("action")) == action for item in audits.get("items", [])):
            available_actions.add(action)
    return sorted(required_actions - available_actions)


def main() -> int:
    args = parse_args()
    prepared = load_prepared_evidence(args.prepared_evidence)
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    health_client = ApiClient(str(prepared["api_health_url"]))
    require_mapping(health_client.request("GET", "/health").body, "API health after restart")
    require_mapping(health_client.request("GET", "/ready").body, "API readiness after restart")
    client = ApiClient(str(prepared["base_url"]))
    client.login(
        str(prepared["tenant_slug"]),
        str(prepared["admin_email"]),
        admin_password,
    )

    project = require_mapping(
        client.request("GET", f"/api/v1/projects/{prepared['project_id']}").body,
        "project after restart",
    )
    host = require_mapping(
        client.request("GET", f"/api/v1/assets/{prepared['host_asset_id']}").body,
        "host after restart",
    )
    application = require_mapping(
        client.request("GET", f"/api/v1/assets/{prepared['application_asset_id']}").body,
        "application after restart",
    )
    if host.get("credential_configured") is not True or "credential_ref" in host:
        raise AcceptanceError("persisted host did not preserve credential redaction")
    historical_relations = require_mapping(
        client.request(
            "GET",
            "/api/v1/assets/"
            f"{prepared['host_asset_id']}/relations?direction=incoming&active_only=false",
        ).body,
        "relation history after restart",
    )
    relation = next(
        (
            item
            for item in historical_relations.get("items", [])
            if str(item.get("id")) == str(prepared["relation_id"])
        ),
        None,
    )
    if relation is None or not relation.get("expires_at"):
        raise AcceptanceError("expired relation history was not persisted across restart")

    required_actions = {str(action) for action in prepared["audit_actions_verified"]}
    missing_actions = find_missing_audit_actions(client, required_actions)
    if missing_actions:
        raise AcceptanceError(f"M1 audit actions were not persisted: {missing_actions}")

    evidence = {
        "milestone": "M1",
        "status": "passed",
        "verified_at": datetime.now(UTC).isoformat(),
        "prepared_evidence": str(args.prepared_evidence),
        "base_url": client.base_url.rstrip("/"),
        "api_health_url": health_client.base_url.rstrip("/"),
        "tenant_slug": str(prepared["tenant_slug"]),
        "admin_email": str(prepared["admin_email"]),
        "project_id": str(project["id"]),
        "host_asset_id": str(host["id"]),
        "application_asset_id": str(application["id"]),
        "relation_id": str(relation["id"]),
        "restart_persistence": "passed",
        "credential_reference_redacted": True,
        "audit_lookup_mode": "server_filtered",
        "audit_actions_verified": sorted(required_actions),
        "secrets_recorded": False,
    }
    write_evidence(args.evidence_file, evidence)
    print(f"M1 restart persistence passed; final evidence={args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"M1 persistence verification failed: {error}")
        raise SystemExit(1) from None
