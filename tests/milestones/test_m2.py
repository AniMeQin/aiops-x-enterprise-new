import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import pytest
from aiops_x_api.modules.agent_control.infrastructure.models import EdgeAgent
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_m2_agent_registration_renewal_and_r0_task_acceptance(
    milestone_context: Any,
) -> None:
    client = milestone_context.client
    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
        json={
            "tenant_name": "M2 Acceptance Tenant",
            "tenant_slug": "m2-acceptance",
            "email": "admin@m2.example.test",
            "display_name": "M2 Admin",
            "password": "M2-Secure-Admin1!",
        },
    )
    assert bootstrap.status_code == 201, bootstrap.text
    login = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "m2-acceptance",
            "email": "admin@m2.example.test",
            "password": "M2-Secure-Admin1!",
        },
    )
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    project = client.post(
        "/api/v1/projects",
        headers={**auth, "Idempotency-Key": "m2-acceptance-project"},
        json={"name": "M2 Acceptance", "slug": "m2-acceptance-project"},
    )
    assert project.status_code == 201, project.text
    asset = client.post(
        "/api/v1/assets",
        headers={**auth, "Idempotency-Key": "m2-acceptance-asset"},
        json={
            "asset_id": "M2-LINUX-001",
            "project_id": project.json()["id"],
            "asset_type": "linux",
            "name": "M2 Linux Host",
            "hostname": "m2-linux-001",
            "environment": "test",
        },
    )
    assert asset.status_code == 201, asset.text

    registration = client.post(
        "/api/v1/agents/registration-tokens",
        headers=auth,
        json={
            "project_id": project.json()["id"],
            "asset_id": asset.json()["id"],
            "expires_in_seconds": 300,
        },
    )
    assert registration.status_code == 201, registration.text
    agent_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agent_csr = _csr(agent_key, "m2-agent")
    enrollment_payload = {
        "registration_token": registration.json()["token"],
        "name": "M2 Acceptance Agent",
        "hostname": "m2-linux-001",
        "platform": "linux",
        "architecture": "amd64",
        "version": "m2-acceptance",
        "csr_pem": agent_csr,
        "capabilities": {"actions": ["system.disk_usage"]},
    }
    enrollment = client.post("/api/v1/agents/enroll", json=enrollment_payload)
    assert enrollment.status_code == 201, enrollment.text
    assert client.post("/api/v1/agents/enroll", json=enrollment_payload).status_code == 401
    enrolled = enrollment.json()
    agent_id = enrolled["agent_id"]
    original_headers = _certificate_headers(enrolled["certificate_pem"])

    heartbeat_payload = {
        "hostname": "m2-linux-001",
        "platform": "linux",
        "architecture": "amd64",
        "version": "m2-acceptance",
        "health_status": "healthy",
        "capabilities": {"actions": ["system.disk_usage"]},
    }
    heartbeat = client.post(
        f"/api/v1/agents/{agent_id}/heartbeat",
        headers=original_headers,
        json=heartbeat_payload,
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["status"] == "online"

    renewal_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    renewal_payload = {"csr_pem": _csr(renewal_key, "m2-agent-renewal")}
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/certificate/renew",
            headers=original_headers,
            json=renewal_payload,
        ).status_code
        == 409
    )
    async with milestone_context.session_factory() as session:
        async with session.begin():
            agent = await session.scalar(select(EdgeAgent).where(EdgeAgent.id == UUID(agent_id)))
            assert agent is not None
            agent.certificate_not_after = datetime.now(UTC) + timedelta(hours=1)

    renewal = client.post(
        f"/api/v1/agents/{agent_id}/certificate/renew",
        headers=original_headers,
        json=renewal_payload,
    )
    assert renewal.status_code == 200, renewal.text
    renewed_headers = _certificate_headers(renewal.json()["certificate_pem"])
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=renewed_headers,
            json=heartbeat_payload,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/heartbeat",
            headers=original_headers,
            json=heartbeat_payload,
        ).status_code
        == 401
    )

    task = client.post(
        f"/api/v1/agents/{agent_id}/tasks",
        headers={**auth, "Idempotency-Key": "m2-acceptance-disk-task"},
        json={"action_id": "system.disk_usage", "parameters": {"paths": ["/"]}},
    )
    assert task.status_code == 201, task.text
    dispatched = client.get(f"/api/v1/agents/{agent_id}/tasks/next", headers=renewed_headers)
    assert dispatched.status_code == 200, dispatched.text
    envelope = dispatched.json()
    assert envelope["task_id"] == task.json()["id"]
    task_certificate = x509.load_pem_x509_certificate(
        enrolled["task_signing_certificate_pem"].encode()
    )
    task_public_key = task_certificate.public_key()
    assert isinstance(task_public_key, rsa.RSAPublicKey)
    task_public_key.verify(
        base64.b64decode(envelope["signature"]),
        envelope["signing_payload"].encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    result = client.post(
        f"/api/v1/agents/{agent_id}/tasks/{task.json()['id']}/result",
        headers=renewed_headers,
        json={
            "status": "succeeded",
            "duration_ms": 7,
            "sanitized_output": {
                "filesystems": [{"path": "/", "total_bytes": 1024, "available_bytes": 512}]
            },
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "succeeded"

    audits = client.get("/api/v1/audit-logs?page_size=100", headers=auth)
    actions = {item["action"] for item in audits.json()["items"]}
    assert {
        "agent.registration_token.created",
        "agent.registered",
        "agent.heartbeat.received",
        "agent.certificate.renewed",
        "agent.task.queued",
        "agent.task.dispatched",
        "agent.task.completed",
    } <= actions


def _csr(private_key: rsa.RSAPrivateKey, common_name: str) -> str:
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(private_key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
        .decode()
    )


def _certificate_headers(certificate_pem: str) -> dict[str, str]:
    certificate = x509.load_pem_x509_certificate(certificate_pem.encode())
    return {
        "X-SSL-Client-Verify": "SUCCESS",
        "X-SSL-Client-Serial": format(certificate.serial_number, "x"),
        "X-SSL-Client-Cert": quote(certificate_pem, safe=""),
    }
