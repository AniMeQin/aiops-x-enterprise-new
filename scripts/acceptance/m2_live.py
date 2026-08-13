#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
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
        description="Run live M2 enrollment, mTLS heartbeat, and R0 task acceptance."
    )
    parser.add_argument("--m1-evidence", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, default=Path("/home/qyy/aiops-x"))
    parser.add_argument("--server-address", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def load_m1_evidence(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read M1 evidence: {error}") from error
    if not isinstance(document, dict) or document.get("status") != "passed":
        raise AcceptanceError("M1 evidence is missing or does not show passed status")
    for field in ("base_url", "tenant_slug", "admin_email", "project_id", "host_asset_id"):
        if not document.get(field):
            raise AcceptanceError(f"M1 evidence is missing {field}")
    return document


def run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
    timeout_seconds: int = 900,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed local Docker commands only
            command,
            check=True,
            env=environment,
            text=True,
            capture_output=capture_output,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise AcceptanceError(
            f"command failed without exposing secret values: {command[0]}"
        ) from error


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def local_agent_ready(port: int) -> bool:
    request = Request(f"http://127.0.0.1:{port}/ready", method="GET")
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310 - loopback health endpoint
            body = json.loads(response.read(64 * 1024))
            return bool(response.status == 200 and body.get("status") == "ok")
    except (HTTPError, OSError, TimeoutError, URLError, json.JSONDecodeError):
        return False


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} response was not an object")
    return value


def file_mode(path: Path) -> str:
    return format(stat.S_IMODE(path.stat().st_mode), "04o")


def main() -> int:
    args = parse_args()
    m1 = load_m1_evidence(args.m1_evidence)
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    docker_binary = shutil.which("docker")
    if docker_binary is None:
        raise AcceptanceError("Docker CLI is not available")
    deployment_root = args.deployment_root.resolve()
    current_release = (deployment_root / "current").resolve()
    releases_directory = (deployment_root / "releases").resolve()
    if releases_directory not in current_release.parents:
        raise AcceptanceError("current release resolves outside the releases directory")
    compose_file = current_release / "compose.yaml"
    environment_file = deployment_root / "shared/.env"
    ca_certificate = deployment_root / "shared/pki/agent-ca-cert.pem"
    token_file = deployment_root / "shared/alertmanager-webhook-token"
    for required_path in (compose_file, environment_file, ca_certificate, token_file):
        if not required_path.is_file():
            raise AcceptanceError(f"required deployment file is missing: {required_path}")

    client = ApiClient(str(m1["base_url"]))
    client.login(str(m1["tenant_slug"]), str(m1["admin_email"]), admin_password)
    host_asset_id = str(m1["host_asset_id"])
    project_id = str(m1["project_id"])
    client.request("GET", f"/api/v1/assets/{host_asset_id}")

    started_at = datetime.now(UTC)
    run_id = started_at.strftime("%Y%m%dt%H%M%Sz").lower() + secrets.token_hex(2)
    request_ids: list[str] = []
    registration_response = client.request(
        "POST",
        "/api/v1/agents/registration-tokens",
        payload={
            "project_id": project_id,
            "asset_id": host_asset_id,
            "expires_in_seconds": 900,
        },
        expected={201},
    )
    if registration_response.request_id:
        request_ids.append(registration_response.request_id)
    registration = require_mapping(registration_response.body, "registration token")
    registration_token = str(registration.pop("token"))
    if not registration_token:
        raise AcceptanceError("control plane did not return a registration token")

    compose_environment = os.environ.copy()
    compose_environment.update(
        {
            "AIOPS_PKI_DIR": str(deployment_root / "shared/pki"),
            "AIOPS_ALERTMANAGER_TOKEN_FILE": str(token_file),
        }
    )
    compose_command = [
        docker_binary,
        "compose",
        "--project-directory",
        str(current_release),
        "-f",
        str(compose_file),
        "--env-file",
        str(environment_file),
        "--profile",
        "agent",
    ]
    run_command(
        [*compose_command, "build", "edge-agent"],
        environment=compose_environment,
    )
    compose_config_result = run_command(
        [*compose_command, "config", "--format", "json"],
        environment=compose_environment,
        capture_output=True,
    )
    try:
        compose_config = json.loads(compose_config_result.stdout)
        project_name = str(compose_config["name"])
        edge_agent_config = compose_config["services"]["edge-agent"]
        configured_image = edge_agent_config.get("image")
        image_name = str(configured_image or f"{project_name}-edge-agent")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise AcceptanceError("cannot resolve the configured Edge Agent image name") from error
    if not image_name or any(character.isspace() for character in image_name):
        raise AcceptanceError("configured Edge Agent image name is invalid")
    image_result = run_command(
        [docker_binary, "image", "inspect", "--format", "{{.Id}}", image_name],
        capture_output=True,
    )
    image_id = image_result.stdout.strip()
    if not image_id or any(character.isspace() for character in image_id):
        raise AcceptanceError("cannot resolve the built Edge Agent image ID")

    state_directory = deployment_root / "acceptance/m2" / run_id
    state_directory.mkdir(parents=True, mode=0o700)
    state_directory.chmod(0o700)
    log_file = state_directory / "edge-agent.log"
    port = available_loopback_port()
    container_base = f"aiops-x-m2-{run_id}"
    active_container: str | None = None

    def docker_run(container_name: str, include_token: bool) -> None:
        nonlocal active_container
        agent_environment = os.environ.copy()
        agent_environment.update(
            {
                "AIOPS_CONTROL_PLANE_URL": f"https://{args.server_address}:8443",
                "AIOPS_STATE_DIRECTORY": "/var/lib/aiops-x",
                "AIOPS_CA_CERT_PATH": "/etc/aiops-x/agent-ca-cert.pem",
                "AIOPS_AGENT_LISTEN": f"127.0.0.1:{port}",
                "AIOPS_ALLOW_INSECURE": "false",
                "AIOPS_HEARTBEAT_INTERVAL": "2s",
                "AIOPS_TASK_POLL_INTERVAL": "1s",
                "AIOPS_CERTIFICATE_RENEW_BEFORE": "6h",
            }
        )
        environment_names = [
            "AIOPS_CONTROL_PLANE_URL",
            "AIOPS_STATE_DIRECTORY",
            "AIOPS_CA_CERT_PATH",
            "AIOPS_AGENT_LISTEN",
            "AIOPS_ALLOW_INSECURE",
            "AIOPS_HEARTBEAT_INTERVAL",
            "AIOPS_TASK_POLL_INTERVAL",
            "AIOPS_CERTIFICATE_RENEW_BEFORE",
        ]
        if include_token:
            agent_environment["AIOPS_REGISTRATION_TOKEN"] = registration_token
            environment_names.append("AIOPS_REGISTRATION_TOKEN")
        command = [
            docker_binary,
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
        for environment_name in environment_names:
            command.extend(["--env", environment_name])
        command.extend(
            [
                "--mount",
                f"type=bind,src={state_directory},dst=/var/lib/aiops-x",
                "--mount",
                f"type=bind,src={ca_certificate},dst=/etc/aiops-x/agent-ca-cert.pem,readonly",
                "--mount",
                "type=bind,src=/,dst=/host,readonly",
                image_id,
            ]
        )
        run_command(command, environment=agent_environment, capture_output=True)
        active_container = container_name

    def capture_logs_and_stop() -> None:
        nonlocal active_container
        if not active_container:
            return
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n--- {active_container} ---\n")
            subprocess.run(  # noqa: S603 - fixed Docker log capture
                [docker_binary, "logs", active_container],
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        subprocess.run(  # noqa: S603 - stop only the acceptance container created above
            [docker_binary, "stop", "--time", "10", active_container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        active_container = None

    try:
        docker_run(container_base, include_token=True)
        wait_until(
            "Edge Agent readiness after enrollment",
            lambda: local_agent_ready(port),
            timeout_seconds=args.timeout_seconds,
        )

        def online_agent() -> dict[str, Any] | None:
            page = require_mapping(
                client.request("GET", f"/api/v1/agents?project_id={project_id}&page_size=100").body,
                "Agent page",
            )
            for item in page.get("items", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("asset_id")) == host_asset_id and item.get("status") == "online":
                    return item
            return None

        agent = wait_until(
            "online Agent heartbeat",
            online_agent,
            timeout_seconds=args.timeout_seconds,
        )
        agent_id = str(agent["id"])
        first_heartbeat = str(agent.get("last_heartbeat_at") or "")
        if agent.get("platform") != "linux" or agent.get("version") != "0.1.0":
            raise AcceptanceError("Agent metadata does not match the real Go Agent image")
        if agent.get("capabilities", {}).get("actions") != ["system.disk_usage"]:
            raise AcceptanceError("Agent did not report the registered R0 capability")

        replay = client.request(
            "POST",
            "/api/v1/agents/enroll",
            payload={
                "registration_token": registration_token,
                "name": "M2 rejected replay",
                "hostname": "m2-rejected-replay",
                "platform": "linux",
                "architecture": "amd64",
                "version": "replay-check",
                "csr_pem": "rejected-token-is-checked-before-this-placeholder" * 4,
                "capabilities": {"actions": ["system.disk_usage"]},
            },
            expected={401},
        )
        if replay.request_id:
            request_ids.append(replay.request_id)
        heartbeat_payload = {
            "hostname": "spoofed-client",
            "platform": "linux",
            "architecture": "amd64",
            "version": "spoof-check",
            "health_status": "healthy",
            "capabilities": {"actions": ["system.disk_usage"]},
        }
        spoofed_heartbeat = client.request(
            "POST",
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers={
                "X-SSL-Client-Verify": "SUCCESS",
                "X-SSL-Client-Serial": "1",
                "X-SSL-Client-Cert": "not-a-certificate",
            },
            payload=heartbeat_payload,
            expected={401},
        )
        if spoofed_heartbeat.request_id:
            request_ids.append(spoofed_heartbeat.request_id)

        idempotency_key = f"m2-live-disk-{run_id}"
        task_payload = {
            "action_id": "system.disk_usage",
            "parameters": {"paths": ["/host"]},
            "expires_in_seconds": 300,
        }
        task_response = client.request(
            "POST",
            f"/api/v1/agents/{agent_id}/tasks",
            headers={"Idempotency-Key": idempotency_key},
            payload=task_payload,
            expected={201},
        )
        if task_response.request_id:
            request_ids.append(task_response.request_id)
        task = require_mapping(task_response.body, "Agent task")
        task_id = str(task["id"])
        duplicate = require_mapping(
            client.request(
                "POST",
                f"/api/v1/agents/{agent_id}/tasks",
                headers={"Idempotency-Key": idempotency_key},
                payload=task_payload,
                expected={201},
            ).body,
            "idempotent Agent task",
        )
        if str(duplicate.get("id")) != task_id:
            raise AcceptanceError("task idempotency key produced a second task")

        def completed_task() -> dict[str, Any] | None:
            page = require_mapping(
                client.request("GET", f"/api/v1/agents/{agent_id}/tasks?page_size=100").body,
                "Agent tasks",
            )
            for item in page.get("items", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("id")) == task_id and item.get("status") in {
                    "succeeded",
                    "failed",
                }:
                    return item
            return None

        completed = wait_until(
            "R0 disk task result",
            completed_task,
            timeout_seconds=args.timeout_seconds,
        )
        if completed.get("status") != "succeeded":
            raise AcceptanceError(f"R0 disk task failed with code {completed.get('error_code')!r}")
        filesystems = completed.get("sanitized_output", {}).get("filesystems", [])
        if not filesystems or filesystems[0].get("path") != "/host":
            raise AcceptanceError("R0 disk task did not return the mounted host filesystem")

        identity_file = state_directory / "identity.json"
        ledger_file = state_directory / "task-ledger.json"

        def persisted_agent_state() -> tuple[Path, Path] | None:
            if not identity_file.is_file() or not ledger_file.is_file():
                return None
            try:
                ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return None
            completed_task_ids = ledger.get("completed_task_ids", {})
            if not isinstance(completed_task_ids, dict) or task_id not in completed_task_ids:
                return None
            return identity_file, ledger_file

        # The control plane can expose a completed task a few milliseconds before
        # the Agent has atomically moved its local ledger into place. Wait for the
        # durable idempotency record instead of racing that final local rename.
        wait_until(
            "persisted Agent identity and completed task ledger",
            persisted_agent_state,
            timeout_seconds=args.timeout_seconds,
        )
        identity_mode = file_mode(identity_file)
        ledger_mode = file_mode(ledger_file)
        if identity_mode != "0600" or ledger_mode != "0600":
            raise AcceptanceError(
                "Agent state permissions are unsafe: "
                f"identity={identity_mode}, ledger={ledger_mode}"
            )

        capture_logs_and_stop()
        time.sleep(1)
        docker_run(f"{container_base}-restart", include_token=False)
        wait_until(
            "Edge Agent readiness from persisted identity",
            lambda: local_agent_ready(port),
            timeout_seconds=args.timeout_seconds,
        )

        def heartbeat_advanced() -> dict[str, Any] | None:
            current = online_agent()
            if current and str(current.get("last_heartbeat_at") or "") != first_heartbeat:
                return current
            return None

        restarted_agent = wait_until(
            "heartbeat after identity-only restart",
            heartbeat_advanced,
            timeout_seconds=args.timeout_seconds,
        )
        capture_logs_and_stop()
    finally:
        capture_logs_and_stop()
        registration_token = ""

    audits = require_mapping(
        client.request("GET", "/api/v1/audit-logs?page_size=100").body,
        "audit logs",
    )
    audit_actions = {str(item.get("action")) for item in audits.get("items", [])}
    required_actions = {
        "agent.registration_token.created",
        "agent.registered",
        "agent.heartbeat.received",
        "agent.task.queued",
        "agent.task.dispatched",
        "agent.task.completed",
    }
    missing_actions = sorted(required_actions - audit_actions)
    if missing_actions:
        raise AcceptanceError(f"M2 audit actions are missing: {missing_actions}")

    evidence = {
        "milestone": "M2",
        "status": "basic_gate_passed",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "m1_evidence": str(args.m1_evidence),
        "deployment_release": current_release.name,
        "registration_token_id": str(registration["id"]),
        "registration_token_recorded": False,
        "agent_id": agent_id,
        "agent_certificate_not_after": restarted_agent.get("certificate_not_after"),
        "agent_state_directory": str(state_directory),
        "identity_file_mode": identity_mode,
        "task_ledger_mode": ledger_mode,
        "identity_restart": "passed_without_registration_token",
        "registration_token_replay_status": replay.status,
        "public_gateway_spoofed_identity_status": spoofed_heartbeat.status,
        "agent_metadata_verified": True,
        "task_id": task_id,
        "task_status": completed["status"],
        "task_duration_ms": completed.get("duration_ms"),
        "task_idempotency": "same_task_id_returned",
        "task_output_path": filesystems[0]["path"],
        "audit_actions_verified": sorted(required_actions),
        "request_ids": request_ids,
        "certificate_renewal_live": "not_executed_default_24h_certificate",
        "disconnect_result_replay_live": "not_executed_in_basic_live_gate",
        "secrets_recorded": False,
        "agent_log": str(log_file),
    }
    write_evidence(args.evidence_file, evidence)
    print(f"M2 basic live gate passed; supplemental live cases remain: {args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"M2 live acceptance failed: {error}")
        raise SystemExit(1) from None
