#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote

from live_common import (
    AcceptanceError,
    ApiClient,
    require_secret_environment,
    wait_until,
    write_evidence,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the enterprise/phase-two business loop against a live deployment."
    )
    parser.add_argument("--m1-evidence", type=Path, required=True)
    parser.add_argument("--m2-evidence", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    return parser.parse_args()


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} response was not an object")
    return value


def load_gate(path: Path, milestone: str, statuses: set[str]) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read {milestone} evidence: {error}") from error
    if (
        not isinstance(document, dict)
        or document.get("milestone") != milestone
        or document.get("status") not in statuses
    ):
        raise AcceptanceError(f"{milestone} evidence does not show a passed gate")
    return document


def create(client: ApiClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return require_mapping(
        client.request("POST", path, payload=payload, expected={200, 201}).body,
        path,
    )


def update(client: ApiClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return require_mapping(client.request("PUT", path, payload=payload).body, path)


def main() -> int:
    args = parse_args()
    m1 = load_gate(args.m1_evidence, "M1", {"passed"})
    m2 = load_gate(args.m2_evidence, "M2", {"basic_gate_passed", "passed"})
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    tenant_slug = str(m1.get("tenant_slug") or "")
    admin_email = str(m1.get("admin_email") or "")
    project_id = str(m1.get("project_id") or "")
    asset_id = str(m1.get("host_asset_id") or "")
    if not all((tenant_slug, admin_email, project_id, asset_id)):
        raise AcceptanceError("M1 evidence lacks live enterprise scope fields")

    client = ApiClient(str(m1["base_url"]), timeout_seconds=30)
    admin = client.login(tenant_slug, admin_email, admin_password)
    admin_id = str(admin["id"])
    started_at = datetime.now(UTC)
    run_id = started_at.strftime("%Y%m%dt%H%M%Sz").lower() + secrets.token_hex(2)
    now = datetime.now(UTC)

    role = create(
        client,
        "/api/v1/auth/roles",
        {
            "name": f"enterprise_approver_{run_id}",
            "description": "Enterprise live acceptance approver",
            "permissions": [
                "project:read",
                "asset:read",
                "incident:read",
                "postmortem:write",
                "postmortem:approve",
                "change:read",
                "change:approve",
            ],
        },
    )
    # Keep the random body while deterministically satisfying every configured
    # password class so the live gate cannot fail by chance.
    approver_password = "Ent!A1a" + secrets.token_urlsafe(24)
    approver_email = f"enterprise-approver-{run_id}@example.test"
    approver = create(
        client,
        "/api/v1/auth/users",
        {
            "email": approver_email,
            "display_name": f"Enterprise Approver {run_id}",
            "password": approver_password,
            "role_ids": [role["id"]],
        },
    )
    department = create(
        client,
        "/api/v1/auth/departments",
        {"name": f"SRE {run_id}", "description": "Live acceptance department"},
    )
    group = create(
        client,
        "/api/v1/auth/groups",
        {"name": f"CAB {run_id}", "department_id": department["id"]},
    )
    client.request(
        "PUT",
        f"/api/v1/auth/departments/{department['id']}/members",
        payload={"user_ids": [approver["id"]]},
        expected={204},
    )
    client.request(
        "PUT",
        f"/api/v1/auth/groups/{group['id']}/members",
        payload={"user_ids": [approver["id"]]},
        expected={204},
    )
    membership = create(
        client,
        "/api/v1/auth/project-memberships",
        {
            "project_id": project_id,
            "subject_type": "group",
            "subject_id": group["id"],
            "access_level": "approver",
            "environment_constraints": ["test"],
            "asset_tag_constraints": ["acceptance", "m1"],
            "gxp_access": False,
        },
    )
    operator_membership = create(
        client,
        "/api/v1/auth/project-memberships",
        {
            "project_id": project_id,
            "subject_type": "user",
            "subject_id": approver["id"],
            "access_level": "operator",
            "environment_constraints": ["test"],
            "asset_tag_constraints": ["acceptance", "m1"],
            "gxp_access": False,
        },
    )
    # Access grants are captured in the access token at login time.
    approver_client = ApiClient(client.base_url, timeout_seconds=30)
    approver_client.login(tenant_slug, approver_email, approver_password)

    issued = create(
        client,
        "/api/v1/auth/api-tokens",
        {
            "name": f"enterprise-readonly-{run_id}",
            "permissions": ["project:read", "asset:read"],
            "project_ids": [project_id],
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
    )
    token = str(issued.pop("token"))
    token_client = ApiClient(client.base_url)
    token_client.access_token = token
    token_client.request("GET", f"/api/v1/projects/{project_id}")

    evidence = create(
        client,
        "/api/v1/evidence",
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "evidence_type": "health_check",
            "title": f"Enterprise health evidence {run_id}",
            "summary": "Live API, database, and Edge Agent gates passed",
            "source_type": "acceptance",
            "source_ref": f"acceptance://enterprise/{run_id}/health",
            "content_hash": sha256(run_id.encode()).hexdigest(),
            "classification": "internal",
            "gxp_classification": "non_gxp",
            "observed_at": now.isoformat(),
            "metadata": {"m1": m1["status"], "m2": m2["status"]},
        },
    )
    evidence_id = str(evidence["id"])
    incident = create(
        client,
        "/api/v1/incidents",
        {
            "project_id": project_id,
            "title": f"Enterprise controlled incident {run_id}",
            "description": "Evidence-driven live acceptance incident",
            "severity": "critical",
            "owner_id": admin_id,
            "participant_ids": [approver["id"]],
            "asset_ids": [asset_id],
            "evidence_ids": [evidence_id],
            "impact_scope": {"environment": "test"},
        },
    )
    incident_id = str(incident["id"])
    create(
        client,
        f"/api/v1/incidents/{incident_id}/timeline",
        {
            "occurred_at": now.isoformat(),
            "entry_type": "evidence",
            "title": "Live evidence attached",
            "evidence_ids": [evidence_id],
        },
    )
    for status in ("acknowledged", "investigating", "resolved"):
        client.request("PATCH", f"/api/v1/incidents/{incident_id}", payload={"status": status})
    client.request(
        "PATCH",
        f"/api/v1/incidents/{incident_id}",
        payload={"status": "closed"},
        expected={409},
    )
    postmortem_payload = {
        "status": "draft",
        "summary": "Enterprise live loop recovered",
        "root_cause": "Controlled acceptance scenario",
        "action_items": [{"owner": "SRE", "action": "Retain automated verification"}],
        "evidence_ids": [evidence_id],
    }
    update(client, f"/api/v1/incidents/{incident_id}/postmortem", postmortem_payload)
    postmortem_payload["status"] = "approved"
    approved_review = update(
        approver_client,
        f"/api/v1/incidents/{incident_id}/postmortem",
        postmortem_payload,
    )
    if str(approved_review.get("approved_by")) != str(approver["id"]):
        raise AcceptanceError("postmortem was not approved by the independent approver")
    client.request("PATCH", f"/api/v1/incidents/{incident_id}", payload={"status": "closed"})

    change = create(
        client,
        "/api/v1/changes",
        {
            "project_id": project_id,
            "title": f"Enterprise controlled change {run_id}",
            "description": "R2 approval and execution-state live acceptance",
            "change_type": "normal",
            "risk_level": "R2",
            "affected_asset_ids": [asset_id],
            "incident_ids": [incident_id],
            "evidence_ids": [evidence_id],
            "precheck_plan": [{"step": "Verify M1 and M2 evidence"}],
            "implementation_plan": [{"step": "Advance registered workflow only"}],
            "validation_plan": [{"step": "Verify health and audit chain"}],
            "success_criteria": [{"condition": "All live gates pass"}],
            "rollback_plan": [{"step": "Stop state transition"}],
            "scheduled_start": (now - timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(minutes=30)).isoformat(),
        },
    )
    change_id = str(change["id"])
    create(client, f"/api/v1/changes/{change_id}/submit", {})
    client.request(
        "POST",
        f"/api/v1/changes/{change_id}/decisions",
        payload={"decision": "approved", "comment": "self approval must fail"},
        expected={403},
    )
    create(
        approver_client,
        f"/api/v1/changes/{change_id}/decisions",
        {"decision": "approved", "comment": "Independent live CAB approval"},
    )
    for status in ("scheduled", "in_progress", "validating", "completed"):
        state = create(client, f"/api/v1/changes/{change_id}/status", {"status": status})
        if state.get("status") != status:
            raise AcceptanceError(f"change did not reach {status}")

    content = f"When enterprise run {run_id} is degraded, verify the database and recent changes."
    content_hash = sha256(content.encode()).hexdigest()
    document = create(
        client,
        "/api/v1/knowledge/documents",
        {
            "project_id": project_id,
            "title": f"Enterprise SOP {run_id}",
            "document_type": "sop",
            "source_type": "manual",
            "source_ref": f"acceptance://enterprise/{run_id}/sop",
            "mime_type": "text/plain",
            "content_hash": content_hash,
            "classification": "internal",
            "gxp_classification": "non_gxp",
            "allowed_role_names": [],
            "tags": ["acceptance", "enterprise"],
        },
    )
    create(
        client,
        f"/api/v1/knowledge/documents/{document['id']}/chunks",
        {
            "chunk_index": 0,
            "heading": "Verification",
            "content": content,
            "content_hash": content_hash,
            "token_count": 20,
            "evidence_refs": [evidence["evidence_id"]],
        },
    )
    search = require_mapping(
        client.request("GET", f"/api/v1/knowledge/search?q={quote(run_id, safe='')}").body,
        "knowledge search",
    )
    if search.get("total", 0) < 1:
        raise AcceptanceError("knowledge search did not return the live SOP")

    finding = create(
        client,
        "/api/v1/security/findings",
        {
            "project_id": project_id,
            "asset_id": asset_id,
            "source": "enterprise-live",
            "external_id": f"SEC-{run_id}",
            "category": "configuration",
            "title": f"Controlled acceptance finding {run_id}",
            "description": "Normalized live security finding",
            "severity": "medium",
            "cve_ids": [],
            "evidence_ids": [evidence_id],
            "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "remediation": {"recommendation": "Keep the validation gate enabled"},
            "risk": {"likelihood": 2, "impact": 3},
            "ticket": {"system": "internal", "external_id": f"SEC-{run_id}"},
        },
    )
    client.request(
        "PATCH",
        f"/api/v1/security/findings/{finding['id']}/status",
        payload={"status": "accepted", "reason": "Controlled test-environment acceptance"},
    )

    slo = create(
        client,
        "/api/v1/reliability/slos",
        {
            "project_id": project_id,
            "name": f"Live availability {run_id}",
            "service_ref": "service://api",
            "sli_type": "availability",
            "prometheus_query": "vector(0.9995)",
            "target": 0.999,
            "warning_burn_rate": 1,
            "critical_burn_rate": 2,
        },
    )
    evaluation = create(client, f"/api/v1/reliability/slos/{slo['id']}/evaluate", {})
    if float(evaluation.get("indicator_value", 0)) != 0.9995:
        raise AcceptanceError("Prometheus-backed SLO evaluation returned an unexpected value")
    capacity = create(
        client,
        "/api/v1/reliability/capacity/analyze",
        {
            "project_id": project_id,
            "name": f"Live capacity {run_id}",
            "resource_type": "cpu",
            "service_ref": "service://api",
            "prometheus_query": "vector(50)",
            "lookback_hours": 2,
            "forecast_hours": 2,
            "warning_threshold": 75,
            "critical_threshold": 90,
        },
    )
    if int(require_mapping(capacity.get("result"), "capacity result").get("sample_count", 0)) < 1:
        raise AcceptanceError("capacity analysis did not receive real Prometheus samples")

    report = create(
        client,
        "/api/v1/reports/generate",
        {
            "project_id": project_id,
            "report_type": "incident_postmortem",
            "source_id": incident_id,
            "title": f"Enterprise live report {run_id}",
            "format": "json",
        },
    )
    report_content = client.request("GET", f"/api/v1/reports/{report['id']}/content")
    if sha256(report_content.raw_body).hexdigest() != report.get("content_hash"):
        raise AcceptanceError("downloaded MinIO report hash did not match metadata")
    topology = require_mapping(
        client.request("GET", f"/api/v1/topology?project_id={project_id}").body,
        "topology",
    )
    if not any(str(node.get("id")) == asset_id for node in topology.get("nodes", [])):
        raise AcceptanceError("project topology did not include the live M1 asset")

    builtin_result = require_mapping(
        client.request("POST", "/api/v1/plugins/builtins", payload={}).body,
        "builtin plugin synchronization",
    )
    plugins = client.request("GET", "/api/v1/plugins").body
    if not isinstance(plugins, list) or len(plugins) < 7:
        raise AcceptanceError("the seven built-in plugin contracts are not registered")
    expected_telemetry_states = {
        "prometheus": "available",
        "loki": "available",
        "tempo": "available",
    }

    def available_telemetry() -> dict[str, str] | None:
        telemetry = require_mapping(
            client.request("GET", "/api/v1/telemetry/status").body,
            "telemetry status",
        )
        states = {item["backend"]: item["status"] for item in telemetry["backends"]}
        return states if states == expected_telemetry_states else None

    telemetry_states = wait_until(
        "Prometheus, Loki, and Tempo readiness",
        available_telemetry,
        timeout_seconds=60,
        interval_seconds=2,
    )
    system_info = require_mapping(
        client.request("GET", "/api/v1/system/info").body,
        "system info",
    )

    client.request("DELETE", f"/api/v1/auth/api-tokens/{issued['id']}", expected={204})
    token_client.request("GET", f"/api/v1/projects/{project_id}", expected={401})
    integrity = require_mapping(
        client.request("GET", "/api/v1/audit-logs/integrity").body,
        "audit integrity",
    )
    if integrity.get("valid") is not True:
        raise AcceptanceError("tenant audit hash chain is not valid")
    required_actions = {
        "identity.api_token.used",
        "incident.postmortem.updated",
        "change.approval.decided",
        "knowledge.search.performed",
        "security.finding.status.updated",
        "report.downloaded",
        "plugin.builtins.synchronized",
    }
    for action in sorted(required_actions):
        page = require_mapping(
            client.request(
                "GET", f"/api/v1/audit-logs?page_size=1&action={quote(action, safe='')}"
            ).body,
            f"audit action {action}",
        )
        if not page.get("items"):
            raise AcceptanceError(f"required enterprise audit action is missing: {action}")

    evidence_document = {
        "milestone": "ENTERPRISE",
        "status": "passed",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "deployment_release": m2.get("deployment_release"),
        "m1_evidence": str(args.m1_evidence),
        "m2_evidence": str(args.m2_evidence),
        "project_id": project_id,
        "asset_id": asset_id,
        "department_id": str(department["id"]),
        "group_id": str(group["id"]),
        "project_membership_id": str(membership["id"]),
        "operator_membership_id": str(operator_membership["id"]),
        "evidence_id": evidence_id,
        "incident_id": incident_id,
        "change_id": change_id,
        "knowledge_document_id": str(document["id"]),
        "security_finding_id": str(finding["id"]),
        "slo_id": str(slo["id"]),
        "capacity_analysis_id": str(capacity["id"]),
        "report_id": str(report["id"]),
        "report_hash_verified": True,
        "builtin_plugins_registered": len(plugins),
        "builtin_sync_registered": len(builtin_result.get("registered", [])),
        "telemetry_backends": telemetry_states,
        "system_ai_state": system_info.get("ai"),
        "audit_chain_valid": True,
        "audit_entries_checked": integrity.get("checked_entries"),
        "audit_actions_verified": sorted(required_actions),
        "secrets_recorded": False,
    }
    write_evidence(args.evidence_file, evidence_document)
    approver_password = ""
    token = ""
    print(f"Enterprise live business loop passed; evidence={args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"Enterprise live acceptance failed: {error}")
        raise SystemExit(1) from None
