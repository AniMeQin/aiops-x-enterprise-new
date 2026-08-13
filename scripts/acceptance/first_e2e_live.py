#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from live_common import (
    AcceptanceError,
    ApiClient,
    require_secret_environment,
    wait_until,
    write_evidence,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the first full Prometheus-to-Alertmanager-to-Agent live business chain."
    )
    parser.add_argument("--m1-evidence", type=Path, required=True)
    parser.add_argument("--m2-evidence", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, default=Path("/home/qyy/aiops-x"))
    parser.add_argument("--server-address", required=True)
    parser.add_argument(
        "--alert-name",
        required=True,
        help=(
            "Name of an already loaded Prometheus alert rule. The operator must trigger and "
            "recover its real monitored condition while this gate is running."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def load_evidence(path: Path, milestone: str, status: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read {milestone} evidence: {error}") from error
    if not isinstance(value, dict) or value.get("milestone") != milestone:
        raise AcceptanceError(f"invalid {milestone} evidence")
    if value.get("status") != status:
        raise AcceptanceError(f"{milestone} evidence does not show {status}")
    return value


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} was not an object")
    return value


def _promql_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _as_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AcceptanceError("API timestamp was not ISO-8601") from error
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed Docker commands only
            command,
            check=True,
            env=environment,
            text=True,
            capture_output=capture_output,
            timeout=180,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise AcceptanceError(
            f"command failed without exposing secret values: {command[0]}"
        ) from error


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def json_request(method: str, url: str, payload: Any | None = None) -> Any:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed loopback endpoints
            raw = response.read(1024 * 1024)
    except (HTTPError, OSError, TimeoutError, URLError) as error:
        raise AcceptanceError(f"local observability request failed: {method}") from error
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError("local observability response was not JSON") from error


def main() -> int:
    args = parse_args()
    m1 = load_evidence(args.m1_evidence, "M1", "passed")
    m2 = load_evidence(args.m2_evidence, "M2", "passed")
    current_release = (args.deployment_root / "current").resolve()
    if m2.get("deployment_release") != current_release.name:
        raise AcceptanceError("M2 evidence belongs to another release")
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    docker = shutil.which("docker")
    if docker is None:
        raise AcceptanceError("Docker CLI is unavailable")

    deployment_root = args.deployment_root.resolve()
    environment_file = deployment_root / "shared/.env"
    ca_certificate = deployment_root / "shared/pki/agent-ca-cert.pem"
    state_directory = Path(str(m2.get("agent_state_directory") or "")).resolve()
    if not all(path.is_file() for path in (environment_file, ca_certificate)):
        raise AcceptanceError("deployment environment or Agent CA is missing")
    if not (state_directory / "identity.json").is_file():
        raise AcceptanceError("passed M2 Agent identity is missing")

    client = ApiClient(str(m1["base_url"]), timeout_seconds=30)
    client.login(str(m1["tenant_slug"]), str(m1["admin_email"]), admin_password)
    project_id = str(m1["project_id"])
    asset_id = str(m1["host_asset_id"])
    agent_id = str(m2["agent_id"])
    project = require_mapping(
        client.request("GET", f"/api/v1/projects/{project_id}").body,
        "M1 project",
    )
    require_mapping(
        client.request("GET", f"/api/v1/assets/{asset_id}").body,
        "M1 asset",
    )
    project_slug = str(project["slug"])
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dt%H%M%Sz").lower() + secrets.token_hex(2)

    targets = require_mapping(
        client.request(
            "GET", f"/api/v1/monitoring/targets?project_id={project_id}&page_size=100"
        ).body,
        "monitoring target page",
    )
    matching_targets = [
        item
        for item in targets.get("items", [])
        if isinstance(item, dict)
        and item.get("enabled") is True
        and isinstance(item.get("binding"), dict)
        and str(item["binding"].get("asset_id")) == asset_id
        and item["binding"].get("enabled") is True
        and item["binding"].get("purpose") == "node_metrics"
    ]
    if len(matching_targets) != 1:
        raise AcceptanceError("M1 asset does not have exactly one enabled node metric binding")
    monitor_target = matching_targets[0]
    binding = require_mapping(monitor_target["binding"], "asset monitoring binding")
    verification = require_mapping(
        client.request(
            "POST", f"/api/v1/monitoring/targets/{monitor_target['id']}/verify", payload={}
        ).body,
        "monitoring target verification",
    )
    if verification.get("status") != "verified":
        raise AcceptanceError("M1 asset monitoring target identity was not verified")

    expected_labels = {
        "job": str(monitor_target["prometheus_job"]),
        "instance": str(monitor_target["prometheus_instance"]),
        "aiops_tenant_slug": str(m1["tenant_slug"]),
        "aiops_project_slug": project_slug,
        str(binding["identity_label"]): str(binding["identity_value"]),
    }
    exact_selector = ",".join(
        f'{key}="{_promql_label(value)}"' for key, value in expected_labels.items()
    )
    exact_up_query = "up{" + exact_selector + "}"
    prometheus = require_mapping(
        json_request(
            "GET",
            "http://127.0.0.1:9090/api/v1/query?query=" + quote(exact_up_query, safe=""),
        ),
        "exact Prometheus asset target query",
    )
    results = prometheus.get("data", {}).get("result", [])
    if prometheus.get("status") != "success" or len(results) != 1:
        raise AcceptanceError("Prometheus did not return exactly one bound M1 asset target")
    metric = require_mapping(results[0].get("metric"), "Prometheus target labels")
    value = results[0].get("value", [])
    if any(metric.get(key) != expected for key, expected in expected_labels.items()):
        raise AcceptanceError("Prometheus target labels do not match the stored asset binding")
    if len(value) != 2 or value[1] != "1":
        raise AcceptanceError("the exactly bound M1 asset target is not up")

    rules = require_mapping(
        json_request("GET", "http://127.0.0.1:9090/api/v1/rules?type=alert"),
        "Prometheus alert rules",
    )
    loaded_rules = [
        rule
        for group in rules.get("data", {}).get("groups", [])
        if isinstance(group, dict)
        for rule in group.get("rules", [])
        if isinstance(rule, dict) and rule.get("type") == "alerting"
    ]
    selected_rules = [rule for rule in loaded_rules if rule.get("name") == args.alert_name]
    if len(selected_rules) != 1 or selected_rules[0].get("health") != "ok":
        raise AcceptanceError("required Prometheus alert rule is not uniquely loaded and healthy")

    compose_environment = os.environ.copy()
    compose_environment.update(
        {
            "AIOPS_PKI_DIR": str(deployment_root / "shared/pki"),
            "AIOPS_ALERTMANAGER_TOKEN_FILE": str(
                deployment_root / "shared/alertmanager-webhook-token"
            ),
        }
    )
    compose = [
        docker,
        "compose",
        "--project-directory",
        str(current_release),
        "-f",
        str(current_release / "compose.yaml"),
        "--env-file",
        str(environment_file),
        "--profile",
        "agent",
    ]
    config = json.loads(
        run_command(
            [*compose, "config", "--format", "json"],
            environment=compose_environment,
            capture_output=True,
        ).stdout
    )
    try:
        project_name = str(config["name"])
        image = str(config["services"]["edge-agent"].get("image") or f"{project_name}-edge-agent")
    except (KeyError, TypeError) as error:
        raise AcceptanceError("cannot resolve Edge Agent image") from error
    container_name = f"aiops-x-first-e2e-{run_id}"
    log_file = state_directory / f"first-e2e-{run_id}.log"
    active = False

    def stop_agent() -> None:
        nonlocal active
        if not active:
            return
        with log_file.open("a", encoding="utf-8") as handle:
            subprocess.run(  # noqa: S603 - logs for the owned acceptance container only
                [docker, "logs", container_name],
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        subprocess.run(  # noqa: S603 - owned acceptance container only
            [docker, "rm", "--force", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        active = False

    def agent_record() -> dict[str, Any] | None:
        page = require_mapping(
            client.request("GET", f"/api/v1/agents?project_id={project_id}&page_size=100").body,
            "Agent page",
        )
        return next(
            (
                item
                for item in page.get("items", [])
                if isinstance(item, dict) and str(item.get("id")) == agent_id
            ),
            None,
        )

    try:
        agent_environment = os.environ.copy()
        agent_environment.update(
            {
                "AIOPS_CONTROL_PLANE_URL": f"https://{args.server_address}:8443",
                "AIOPS_STATE_DIRECTORY": "/var/lib/aiops-x",
                "AIOPS_CA_CERT_PATH": "/etc/aiops-x/agent-ca-cert.pem",
                "AIOPS_AGENT_LISTEN": f"127.0.0.1:{available_loopback_port()}",
                "AIOPS_ALLOW_INSECURE": "false",
                "AIOPS_HEARTBEAT_INTERVAL": "2s",
                "AIOPS_TASK_POLL_INTERVAL": "1s",
                "AIOPS_CERTIFICATE_RENEW_BEFORE": "6h",
            }
        )
        command = [
            docker,
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--network",
            "host",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
        ]
        for variable in (
            "AIOPS_CONTROL_PLANE_URL",
            "AIOPS_STATE_DIRECTORY",
            "AIOPS_CA_CERT_PATH",
            "AIOPS_AGENT_LISTEN",
            "AIOPS_ALLOW_INSECURE",
            "AIOPS_HEARTBEAT_INTERVAL",
            "AIOPS_TASK_POLL_INTERVAL",
            "AIOPS_CERTIFICATE_RENEW_BEFORE",
        ):
            command.extend(["--env", variable])
        command.extend(
            [
                "--mount",
                f"type=bind,src={state_directory},dst=/var/lib/aiops-x",
                "--mount",
                f"type=bind,src={ca_certificate},dst=/etc/aiops-x/agent-ca-cert.pem,readonly",
                "--mount",
                "type=bind,src=/,dst=/host,readonly",
                image,
            ]
        )
        run_command(command, environment=agent_environment, capture_output=True)
        active = True
        wait_until(
            "passed M2 Agent online for first E2E",
            lambda: (record := agent_record()) and record.get("status") == "online",
            timeout_seconds=args.timeout_seconds,
        )

        alert_wait_started_at = datetime.now(UTC)

        def delivered_event() -> dict[str, Any] | None:
            page = require_mapping(
                client.request("GET", f"/api/v1/events?project_id={project_id}&page_size=100").body,
                "Event page",
            )
            for item in page.get("items", []):
                if not isinstance(item, dict) or str(item.get("primary_asset_id")) != asset_id:
                    continue
                if _as_utc(str(item.get("first_seen_at"))) < alert_wait_started_at:
                    continue
                detail = require_mapping(
                    client.request("GET", f"/api/v1/events/{item['id']}").body,
                    "candidate Event detail",
                )
                for alert in detail.get("alerts", []):
                    labels = alert.get("labels", {}) if isinstance(alert, dict) else {}
                    if labels.get("alertname") != args.alert_name:
                        continue
                    if all(labels.get(key) == value for key, value in expected_labels.items()):
                        return item
            return None

        event = wait_until(
            "real Prometheus rule, Alertmanager delivery and Event creation",
            delivered_event,
            timeout_seconds=args.timeout_seconds,
            interval_seconds=2,
        )
        event_id = str(event["id"])
        detail = require_mapping(
            client.request("GET", f"/api/v1/events/{event_id}").body,
            "Event detail",
        )
        alerts = detail.get("alerts", [])
        matching_alerts = [
            alert
            for alert in alerts
            if isinstance(alert, dict)
            and alert.get("source") == "alertmanager"
            and alert.get("labels", {}).get("alertname") == args.alert_name
            and all(
                alert.get("labels", {}).get(key) == value for key, value in expected_labels.items()
            )
        ]
        if len(matching_alerts) != 1:
            raise AcceptanceError("Event did not preserve one identity-matched rule alert")
        evidence_refs = detail.get("timeline", [])[0].get("evidence_refs", [])
        metric_evidence = next(
            (item for item in evidence_refs if item.get("type") == "prometheus_query"),
            None,
        )
        evidence_samples = (
            metric_evidence.get("samples", []) if isinstance(metric_evidence, dict) else []
        )
        if (
            not metric_evidence
            or metric_evidence.get("status") != "collected"
            or not evidence_samples
        ):
            raise AcceptanceError("Event did not preserve collected Prometheus evidence")
        evidence_metric = require_mapping(
            evidence_samples[0].get("metric"), "Event Prometheus evidence labels"
        )
        if any(evidence_metric.get(key) != value for key, value in expected_labels.items()):
            raise AcceptanceError("Event Prometheus evidence does not match the asset binding")

        runbook = require_mapping(
            client.request(
                "POST",
                "/api/v1/runbooks/builtins",
                payload={"project_id": project_id},
                expected={201},
            ).body,
            "builtin R0 runbook",
        )
        job = require_mapping(
            client.request(
                "POST",
                "/api/v1/automation/jobs",
                headers={"Idempotency-Key": f"first-e2e-job-{run_id}"},
                payload={
                    "runbook_id": runbook["id"],
                    "runbook_version": 1,
                    "asset_id": asset_id,
                    "event_id": event_id,
                    "inputs": {"paths": ["/host"]},
                },
                expected={201},
            ).body,
            "R0 automation job",
        )
        job_id = str(job["id"])

        def completed_job() -> dict[str, Any] | None:
            current = require_mapping(
                client.request("GET", f"/api/v1/automation/jobs/{job_id}").body,
                "automation job",
            )
            return current if current.get("status") in {"succeeded", "failed"} else None

        completed = wait_until(
            "real Agent R0 Runbook completion",
            completed_job,
            timeout_seconds=args.timeout_seconds,
        )
        if completed.get("status") != "succeeded":
            raise AcceptanceError(f"first E2E R0 job failed: {completed.get('error_code')}")
        filesystems = completed.get("sanitized_output", {}).get("filesystems", [])
        if not filesystems or filesystems[0].get("path") != "/host":
            raise AcceptanceError("first E2E Runbook result is missing the host filesystem")

        ai = require_mapping(
            client.request("POST", f"/api/v1/ai/events/{event_id}/summary", payload={}).body,
            "AI event summary",
        )
        if ai.get("status") not in {"completed", "not_configured"}:
            raise AcceptanceError("AI analysis was neither evidence-backed nor explicitly disabled")
        final_detail = require_mapping(
            client.request("GET", f"/api/v1/events/{event_id}").body,
            "completed Event detail",
        )
        if not any(
            item.get("category") == "automation" and item.get("title") == "Runbook 执行成功"
            for item in final_detail.get("timeline", [])
        ):
            raise AcceptanceError("Event timeline is missing successful Runbook execution")

        required_audits = {
            "alert.created",
            "event.auto_created",
            "runbook.published",
            "automation.job.requested",
            "automation.job.completed",
            "ai.analysis.skipped",
        }
        for action in sorted(required_audits):
            audits = require_mapping(
                client.request(
                    "GET", f"/api/v1/audit-logs?page_size=1&action={quote(action, safe='')}"
                ).body,
                f"audit action {action}",
            )
            if not audits.get("items"):
                raise AcceptanceError(f"required first E2E audit is missing: {action}")

        def resolved_event() -> dict[str, Any] | None:
            current = require_mapping(
                client.request("GET", f"/api/v1/events/{event_id}").body,
                "recovering Event detail",
            )
            current_alerts = current.get("alerts", [])
            if current.get("status") != "resolved":
                return None
            if not current_alerts or any(
                alert.get("status") != "resolved"
                for alert in current_alerts
                if isinstance(alert, dict)
            ):
                return None
            return current

        wait_until(
            "real monitored condition recovery, Alertmanager resolution and Event resolution",
            resolved_event,
            timeout_seconds=args.timeout_seconds,
            interval_seconds=2,
        )
        required_audits.add("alert.resolved")
        resolved_audits = require_mapping(
            client.request("GET", "/api/v1/audit-logs?page_size=1&action=alert.resolved").body,
            "audit action alert.resolved",
        )
        if not resolved_audits.get("items"):
            raise AcceptanceError("required first E2E recovery audit is missing")
    finally:
        stop_agent()

    evidence = {
        "milestone": "FIRST_E2E",
        "status": "passed",
        "run_id": run_id,
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "deployment_release": current_release.name,
        "m1_evidence": str(args.m1_evidence),
        "m2_evidence": str(args.m2_evidence),
        "monitor_target_id": str(monitor_target["id"]),
        "monitor_binding_id": str(binding["id"]),
        "monitor_target_verification": "verified",
        "prometheus_exact_asset_target_up": True,
        "prometheus_alert_rule": args.alert_name,
        "alertmanager_delivery": "passed_via_real_prometheus_rule",
        "manual_alert_injection": False,
        "event_id": event_id,
        "event_prometheus_evidence": "collected",
        "event_prometheus_identity": "matched_asset_binding",
        "agent_id": agent_id,
        "runbook_id": str(runbook["id"]),
        "automation_job_id": job_id,
        "automation_job_status": completed["status"],
        "automation_output_path": filesystems[0]["path"],
        "event_automation_timeline": "passed",
        "event_recovery": "resolved_via_real_rule_recovery",
        "ai_state": ai["status"],
        "audit_actions_verified": sorted(required_audits),
        "agent_log": str(log_file),
        "secrets_recorded": False,
    }
    write_evidence(args.evidence_file, evidence)
    print(f"First live E2E business chain passed; evidence={args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"First live E2E acceptance failed: {error}")
        raise SystemExit(1) from None
