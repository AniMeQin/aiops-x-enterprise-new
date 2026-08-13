#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from live_common import (
    AcceptanceError,
    ApiClient,
    require_secret_environment,
    wait_until,
    write_evidence,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Complete M2 with a live result-upload outage and lost-response "
            "certificate-renewal recovery."
        )
    )
    parser.add_argument("--m1-evidence", type=Path, required=True)
    parser.add_argument("--m2-basic-evidence", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, default=Path("/home/qyy/aiops-x"))
    parser.add_argument("--server-address", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def load_evidence(path: Path, milestone: str, status: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read {milestone} evidence: {error}") from error
    if not isinstance(document, dict) or document.get("milestone") != milestone:
        raise AcceptanceError(f"invalid {milestone} evidence")
    if document.get("status") != status:
        raise AcceptanceError(f"{milestone} evidence does not show {status}")
    return document


def run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
    timeout_seconds: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed Docker/OpenSSL commands only
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


def require_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{description} was not an object")
    return value


def file_mode(path: Path) -> str:
    return format(stat.S_IMODE(path.stat().st_mode), "04o")


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot read persisted Agent state: {path.name}") from error
    return require_mapping(value, path.name)


def certificate_serial(identity_path: Path) -> str:
    certificate = str(read_json(identity_path).get("certificate_pem") or "")
    if "BEGIN CERTIFICATE" not in certificate:
        raise AcceptanceError("Agent identity does not contain a certificate")
    openssl = shutil.which("openssl")
    if openssl is None:
        raise AcceptanceError("OpenSSL is not available")
    result = subprocess.run(  # noqa: S603 - resolved OpenSSL metadata read only
        [openssl, "x509", "-noout", "-serial"],
        input=certificate,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0 or not result.stdout.startswith("serial="):
        raise AcceptanceError("cannot read Agent certificate serial")
    raw = result.stdout.strip().split("=", 1)[1]
    try:
        return format(int(raw, 16), "x")
    except ValueError:
        raise AcceptanceError("Agent certificate serial is invalid") from None


def pending_csr_hash(identity_path: Path) -> str | None:
    pending = read_json(identity_path).get("pending_renewal")
    if not isinstance(pending, dict) or not pending.get("csr_pem"):
        return None
    return hashlib.sha256(str(pending["csr_pem"]).encode()).hexdigest()


def set_environment_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{name}="
    updated = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = prefix + value
            updated = True
            break
    if not updated:
        lines.append(prefix + value)
    temporary = path.with_name(f".{path.name}.m2-incoming-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def fault_location(mode: str) -> str:
    common = """
    if ($ssl_client_verify != SUCCESS) { return 496; }
    proxy_set_header Host $host;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
    proxy_set_header X-SSL-Client-Serial $ssl_client_serial;
    proxy_set_header X-SSL-Client-Cert $ssl_client_escaped_cert;
"""
    if mode == "result_outage":
        return (
            "  location ~ ^/api/v1/agents/[0-9a-fA-F-]+/tasks/"
            "[0-9a-fA-F-]+/result$ {\n"
            "    proxy_pass http://127.0.0.1:1;\n" + common + "  }\n\n"
        )
    if mode == "renewal_slow_response":
        return (
            "  location ~ ^/api/v1/agents/[0-9a-fA-F-]+/certificate/renew$ {\n"
            "    proxy_pass http://api:8000;\n"
            "    limit_rate 1;\n" + common + "  }\n\n"
        )
    raise AcceptanceError("unknown gateway fault mode")


def main() -> int:
    args = parse_args()
    m1 = load_evidence(args.m1_evidence, "M1", "passed")
    basic = load_evidence(args.m2_basic_evidence, "M2", "basic_gate_passed")
    if basic.get("deployment_release") != Path(args.deployment_root / "current").resolve().name:
        raise AcceptanceError("M2 basic evidence belongs to another release")
    admin_password = require_secret_environment("AIOPS_ACCEPTANCE_ADMIN_PASSWORD")
    docker = shutil.which("docker")
    if docker is None:
        raise AcceptanceError("Docker CLI is not available")

    deployment_root = args.deployment_root.resolve()
    current_release = (deployment_root / "current").resolve()
    compose_file = current_release / "compose.yaml"
    environment_file = deployment_root / "shared/.env"
    pki_directory = deployment_root / "shared/pki"
    ca_certificate = pki_directory / "agent-ca-cert.pem"
    state_directory = Path(str(basic.get("agent_state_directory") or "")).resolve()
    acceptance_root = (deployment_root / "acceptance/m2").resolve()
    if acceptance_root not in state_directory.parents:
        raise AcceptanceError("M2 Agent state directory is outside the acceptance root")
    identity_file = state_directory / "identity.json"
    ledger_file = state_directory / "task-ledger.json"
    for path in (compose_file, environment_file, ca_certificate, identity_file, ledger_file):
        if not path.is_file():
            raise AcceptanceError(f"required file is missing: {path}")

    client = ApiClient(str(m1["base_url"]), timeout_seconds=30)
    client.login(str(m1["tenant_slug"]), str(m1["admin_email"]), admin_password)
    project_id = str(m1["project_id"])
    agent_id = str(basic["agent_id"])
    started_at = datetime.now(UTC)
    run_id = started_at.strftime("%Y%m%dt%H%M%Sz").lower() + secrets.token_hex(2)
    work_directory = state_directory / f"supplemental-{run_id}"
    work_directory.mkdir(mode=0o700)
    work_directory.chmod(0o700)
    environment_backup = work_directory / "shared-environment.backup"
    log_file = work_directory / "edge-agent.log"

    compose_environment = os.environ.copy()
    compose_environment.update(
        {
            "AIOPS_PKI_DIR": str(pki_directory),
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
        str(compose_file),
        "--env-file",
        str(environment_file),
    ]
    compose_config = json.loads(
        run_command(
            [*compose, "--profile", "agent", "config", "--format", "json"],
            environment=compose_environment,
            capture_output=True,
        ).stdout
    )
    try:
        project_name = str(compose_config["name"])
        agent_image = str(
            compose_config["services"]["edge-agent"].get("image") or f"{project_name}-edge-agent"
        )
        gateway_image = str(compose_config["services"]["agent-gateway"]["image"])
    except (KeyError, TypeError) as error:
        raise AcceptanceError("cannot resolve acceptance container images") from error
    network_result = run_command(
        [
            docker,
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--filter",
            "label=com.docker.compose.network=control-plane",
            "--format",
            "{{.Name}}",
        ],
        capture_output=True,
    )
    control_network = network_result.stdout.strip()
    if not control_network or "\n" in control_network:
        raise AcceptanceError("cannot resolve the Compose control-plane network")

    normal_gateway_config = (current_release / "deploy/compose/agent-api-nginx.conf").read_text(
        encoding="utf-8"
    )
    marker = "  location /api/v1/agents/ {"
    if normal_gateway_config.count(marker) != 1:
        raise AcceptanceError("Agent Gateway configuration marker is invalid")

    active_agent: str | None = None
    fault_gateway = f"aiops-x-m2-fault-gateway-{run_id}"
    environment_changed = False

    def restart_api() -> None:
        run_command([*compose, "restart", "api"], environment=compose_environment)
        run_command([*compose, "up", "-d", "--wait", "api"], environment=compose_environment)

    def stop_acceptance_agent() -> None:
        nonlocal active_agent
        if active_agent is None:
            return
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"\n--- {active_agent} ---\n")
            subprocess.run(  # noqa: S603 - logs for the owned acceptance container only
                [docker, "logs", active_agent],
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=30,
            )
        subprocess.run(  # noqa: S603 - owned acceptance container only
            [docker, "rm", "--force", active_agent],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        active_agent = None

    def start_acceptance_agent(suffix: str, renew_before: str) -> None:
        nonlocal active_agent
        if active_agent is not None:
            raise AcceptanceError("an acceptance Agent is already running")
        name = f"aiops-x-m2-supplemental-{run_id}-{suffix}"
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
                "AIOPS_CERTIFICATE_RENEW_BEFORE": renew_before,
            }
        )
        command = [
            docker,
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
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
                agent_image,
            ]
        )
        run_command(command, environment=agent_environment, capture_output=True)
        active_agent = name

    def restore_normal_gateway() -> None:
        subprocess.run(  # noqa: S603 - owned fault gateway only
            [docker, "rm", "--force", fault_gateway],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        run_command(
            [*compose, "up", "-d", "--wait", "agent-gateway"],
            environment=compose_environment,
        )

    def start_fault_gateway(mode: str) -> None:
        run_command([*compose, "stop", "agent-gateway"], environment=compose_environment)
        config_file = work_directory / f"gateway-{mode}.conf"
        config_file.write_text(
            normal_gateway_config.replace(marker, fault_location(mode) + marker),
            encoding="utf-8",
        )
        config_file.chmod(0o600)
        run_command(
            [
                docker,
                "run",
                "--detach",
                "--rm",
                "--name",
                fault_gateway,
                "--network",
                control_network,
                "--publish",
                f"{args.server_address}:8443:8443",
                "--mount",
                f"type=bind,src={config_file},dst=/etc/nginx/conf.d/default.conf,readonly",
                "--mount",
                f"type=bind,src={pki_directory},dst=/etc/aiops-x-pki,readonly",
                gateway_image,
            ],
            capture_output=True,
        )

        curl = shutil.which("curl")
        if curl is None:
            raise AcceptanceError("curl is not available")

        def gateway_ready() -> bool:
            result = subprocess.run(  # noqa: S603 - fixed live TLS probe
                [
                    curl,
                    "--silent",
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code}",
                    "--cacert",
                    str(ca_certificate),
                    f"https://{args.server_address}:8443/api/v1/agents/enroll",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            return result.returncode == 0 and result.stdout == "405"

        wait_until("fault-injection Agent Gateway readiness", gateway_ready, timeout_seconds=30)

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

    def database_certificate_state() -> tuple[str | None, str, str | None]:
        canonical_agent_id = str(UUID(agent_id))
        sql = (
            "SELECT id,COALESCE(previous_certificate_serial,''),certificate_serial,"
            "COALESCE(last_renewal_csr_fingerprint,'') FROM edge_agents"
        )
        result = run_command(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c "{sql}"',
            ],
            environment=compose_environment,
            capture_output=True,
        )
        matched = next(
            (
                line.split("|")
                for line in result.stdout.splitlines()
                if line.startswith(canonical_agent_id + "|")
            ),
            [],
        )
        if len(matched) != 4 or not matched[2]:
            raise AcceptanceError("cannot read Agent certificate metadata from PostgreSQL")
        return matched[1] or None, matched[2].lower(), matched[3] or None

    try:
        # Scenario 1: the real Agent executes the task, but the result endpoint is
        # unavailable. Its local ledger must retain and later replay the result.
        start_fault_gateway("result_outage")
        start_acceptance_agent("disconnect", "6h")
        wait_until(
            "Agent heartbeat through the fault gateway",
            lambda: (record := agent_record()) and record.get("status") == "online",
            timeout_seconds=args.timeout_seconds,
        )
        task = require_mapping(
            client.request(
                "POST",
                f"/api/v1/agents/{agent_id}/tasks",
                headers={"Idempotency-Key": f"m2-disconnect-{run_id}"},
                payload={
                    "action_id": "system.disk_usage",
                    "parameters": {"paths": ["/host"]},
                    "expires_in_seconds": 300,
                },
                expected={201},
            ).body,
            "disconnect task",
        )
        disconnect_task_id = str(task["id"])

        def pending_result() -> bool:
            ledger = read_json(ledger_file)
            pending = ledger.get("pending_results")
            return isinstance(pending, dict) and disconnect_task_id in pending

        wait_until(
            "locally persisted result during gateway outage",
            pending_result,
            timeout_seconds=args.timeout_seconds,
        )
        task_page = require_mapping(
            client.request("GET", f"/api/v1/agents/{agent_id}/tasks?page_size=100").body,
            "Agent task page",
        )
        server_task = next(
            item for item in task_page.get("items", []) if str(item.get("id")) == disconnect_task_id
        )
        if server_task.get("status") != "running":
            raise AcceptanceError("server accepted a result while the result endpoint was blocked")
        restore_normal_gateway()

        def recovered_task() -> dict[str, Any] | None:
            page = require_mapping(
                client.request("GET", f"/api/v1/agents/{agent_id}/tasks?page_size=100").body,
                "Agent task page after recovery",
            )
            return next(
                (
                    item
                    for item in page.get("items", [])
                    if str(item.get("id")) == disconnect_task_id
                    and item.get("status") == "succeeded"
                ),
                None,
            )

        recovered = wait_until(
            "Agent result replay after gateway recovery",
            recovered_task,
            timeout_seconds=args.timeout_seconds,
        )

        def completed_ledger() -> bool:
            ledger = read_json(ledger_file)
            pending = ledger.get("pending_results")
            completed = ledger.get("completed_task_ids")
            return (
                isinstance(pending, dict)
                and disconnect_task_id not in pending
                and isinstance(completed, dict)
                and disconnect_task_id in completed
            )

        wait_until(
            "durable completed-task ledger after replay",
            completed_ledger,
            timeout_seconds=args.timeout_seconds,
        )
        stop_acceptance_agent()

        # Scenario 2: permit this isolated Agent to renew early. The fault gateway
        # commits the first renewal server-side but deliberately withholds its
        # response. The Agent must retain and retry the identical CSR via its old
        # certificate, then atomically activate the recovered identity.
        shutil.copy2(environment_file, environment_backup)
        environment_backup.chmod(0o600)
        set_environment_value(
            environment_file,
            "AIOPS_AGENT_CERTIFICATE_RENEWAL_WINDOW_HOURS",
            "72",
        )
        environment_changed = True
        restart_api()
        initial_serial = certificate_serial(identity_file)
        start_fault_gateway("renewal_slow_response")
        start_acceptance_agent("renewal", "25h")
        first_csr_hash = wait_until(
            "persisted pending renewal CSR",
            lambda: pending_csr_hash(identity_file),
            timeout_seconds=args.timeout_seconds,
        )

        def first_renewal_committed() -> tuple[str | None, str, str | None] | None:
            state = database_certificate_state()
            return state if state[0] == initial_serial and state[1] != initial_serial else None

        first_server_state = wait_until(
            "first server-side renewal commit",
            first_renewal_committed,
            timeout_seconds=args.timeout_seconds,
        )
        subprocess.run(  # noqa: S603 - owned fault gateway only
            [docker, "rm", "--force", fault_gateway],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        csr_hash_after_lost_response = pending_csr_hash(identity_file)
        if csr_hash_after_lost_response != first_csr_hash:
            raise AcceptanceError("Agent did not preserve the pending CSR after response loss")
        restore_normal_gateway()

        def renewed_identity() -> tuple[str, tuple[str | None, str, str | None]] | None:
            if pending_csr_hash(identity_file) is not None:
                return None
            current_serial = certificate_serial(identity_file)
            database_state = database_certificate_state()
            if current_serial == initial_serial or database_state[1] != current_serial:
                return None
            return current_serial, database_state

        final_serial, final_server_state = wait_until(
            "same-CSR certificate renewal recovery",
            renewed_identity,
            timeout_seconds=args.timeout_seconds,
        )
        if final_serial == first_server_state[1]:
            raise AcceptanceError(
                "lost renewal response was not retried through the previous certificate"
            )
        audit_page = require_mapping(
            client.request(
                "GET", "/api/v1/audit-logs?page_size=100&action=agent.certificate.renewed"
            ).body,
            "certificate renewal audits",
        )
        renewal_audits = [
            item for item in audit_page.get("items", []) if str(item.get("resource_id")) == agent_id
        ]
        if len(renewal_audits) < 2 or not any(
            item.get("metadata_json", {}).get("retry_via_previous_certificate") is True
            for item in renewal_audits
            if isinstance(item, dict)
        ):
            raise AcceptanceError("previous-certificate renewal recovery audit is missing")
        heartbeat_before_restore = str((agent_record() or {}).get("last_heartbeat_at") or "")
        stop_acceptance_agent()

        shutil.copy2(environment_backup, environment_file)
        environment_file.chmod(0o600)
        environment_backup.unlink()
        environment_changed = False
        restart_api()
        start_acceptance_agent("baseline", "6h")

        def baseline_heartbeat() -> dict[str, Any] | None:
            record = agent_record()
            if record and str(record.get("last_heartbeat_at") or "") != heartbeat_before_restore:
                return record
            return None

        wait_until(
            "heartbeat after restoring baseline renewal policy",
            baseline_heartbeat,
            timeout_seconds=args.timeout_seconds,
        )
        stop_acceptance_agent()
    finally:
        stop_acceptance_agent()
        try:
            restore_normal_gateway()
        except AcceptanceError:
            pass
        if environment_changed and environment_backup.is_file():
            shutil.copy2(environment_backup, environment_file)
            environment_file.chmod(0o600)
            environment_backup.unlink()
            try:
                restart_api()
            except AcceptanceError:
                pass

    required_audits = {
        "agent.task.dispatched",
        "agent.task.completed",
        "agent.certificate.renewed",
    }
    for action in sorted(required_audits):
        page = require_mapping(
            client.request("GET", f"/api/v1/audit-logs?page_size=1&action={action}").body,
            f"audit action {action}",
        )
        if not page.get("items"):
            raise AcceptanceError(f"required supplemental audit action is missing: {action}")

    evidence = {
        **basic,
        "status": "passed",
        "basic_evidence": str(args.m2_basic_evidence),
        "supplemental_run_id": run_id,
        "supplemental_started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "disconnect_result_replay_live": "passed",
        "disconnect_task_id": disconnect_task_id,
        "disconnect_server_status_before_recovery": "running",
        "disconnect_recovered_status": recovered["status"],
        "disconnect_output_path": recovered["sanitized_output"]["filesystems"][0]["path"],
        "disconnect_pending_ledger_observed": True,
        "disconnect_completed_ledger_observed": True,
        "certificate_renewal_live": "passed_with_lost_response_same_csr_recovery",
        "renewal_initial_serial": initial_serial,
        "renewal_first_unacknowledged_serial": first_server_state[1],
        "renewal_final_serial": final_serial,
        "renewal_previous_serial": final_server_state[0],
        "renewal_csr_sha256": first_csr_hash,
        "renewal_retry_via_previous_certificate_audited": True,
        "renewal_policy_restored": True,
        "identity_file_mode": file_mode(identity_file),
        "task_ledger_mode": file_mode(ledger_file),
        "supplemental_agent_log": str(log_file),
        "audit_actions_verified": sorted(
            set(str(item) for item in basic.get("audit_actions_verified", [])) | required_audits
        ),
        "secrets_recorded": False,
    }
    write_evidence(args.evidence_file, evidence)
    print(f"M2 supplemental live cases passed; final evidence={args.evidence_file}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"M2 supplemental live acceptance failed: {error}")
        raise SystemExit(1) from None
