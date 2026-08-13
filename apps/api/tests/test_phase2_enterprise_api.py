from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient` is deprecated")
async def test_phase2_enterprise_business_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    stored_reports: dict[str, bytes] = {}

    async def put_report(*, object_name: str, content: bytes, content_type: str) -> str:
        assert content_type.startswith(("application/json", "text/html"))
        stored_reports[object_name] = content
        return f"s3://aiops-reports/{object_name}"

    async def get_report(object_ref: str) -> bytes:
        return stored_reports[object_ref.removeprefix("s3://aiops-reports/")]

    async def prometheus_response(**kwargs: object) -> dict[str, object]:
        if kwargs["path"] == "/api/v1/query":
            return {
                "status": "success",
                "data": {"result": [{"metric": {"service": "api"}, "value": [1, "0.9995"]}]},
            }
        now = datetime.now(UTC).timestamp()
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {"service": "api"},
                        "values": [[now - 7200, "40"], [now - 3600, "45"], [now, "50"]],
                    }
                ]
            },
        }

    monkeypatch.setattr("aiops_x_api.modules.reporting.api.put_report", put_report)
    monkeypatch.setattr("aiops_x_api.modules.reporting.api.get_report", get_report)
    monkeypatch.setattr(
        "aiops_x_api.modules.reliability.api.backend_json_request", prometheus_response
    )

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        admin = _bootstrap_and_login(client)
        auth = admin["auth"]
        admin_id = admin["user_id"]

        project = _post(
            client,
            "/api/v1/projects",
            auth,
            {"name": "Phase Two Project", "slug": "phase-two"},
        )
        project_id = project["id"]
        asset = _post(
            client,
            "/api/v1/assets",
            auth,
            {
                "asset_id": "PHASE2-LINUX-001",
                "project_id": project_id,
                "asset_type": "linux",
                "name": "Phase 2 Linux",
                "environment": "test",
                "criticality": "high",
                "gxp_classification": "non_gxp",
                "tags": ["phase2", "managed"],
            },
        )
        asset_id = asset["id"]

        role = _post(
            client,
            "/api/v1/auth/roles",
            auth,
            {
                "name": "change_approver",
                "permissions": [
                    "project:read",
                    "incident:read",
                    "postmortem:write",
                    "postmortem:approve",
                    "change:read",
                    "change:approve",
                ],
            },
        )
        approver = _post(
            client,
            "/api/v1/auth/users",
            auth,
            {
                "email": "approver@example.test",
                "display_name": "Change Approver",
                "password": "Secure-Approver1!",
                "role_ids": [role["id"]],
            },
        )
        approver_auth = _login(client, "approver@example.test", "Secure-Approver1!")

        department = _post(
            client,
            "/api/v1/auth/departments",
            auth,
            {"name": "SRE", "description": "Site Reliability Engineering"},
        )
        group = _post(
            client,
            "/api/v1/auth/groups",
            auth,
            {"name": "Change Board", "department_id": department["id"]},
        )
        assert (
            client.put(
                f"/api/v1/auth/groups/{group['id']}/members",
                headers=auth,
                json={"user_ids": [approver["id"]]},
            ).status_code
            == 204
        )
        assert (
            client.put(
                f"/api/v1/auth/departments/{department['id']}/members",
                headers=auth,
                json={"user_ids": [approver["id"]]},
            ).status_code
            == 204
        )
        assert client.get(f"/api/v1/auth/groups/{group['id']}/members", headers=auth).json() == [
            approver["id"]
        ]
        membership = _post(
            client,
            "/api/v1/auth/project-memberships",
            auth,
            {
                "project_id": project_id,
                "subject_type": "group",
                "subject_id": group["id"],
                "access_level": "approver",
                "environment_constraints": ["test"],
                "asset_tag_constraints": ["managed"],
                "gxp_access": False,
            },
        )
        operator_membership = _post(
            client,
            "/api/v1/auth/project-memberships",
            auth,
            {
                "project_id": project_id,
                "subject_type": "user",
                "subject_id": approver["id"],
                "access_level": "operator",
                "environment_constraints": ["test"],
                "asset_tag_constraints": ["managed"],
                "gxp_access": False,
            },
        )
        assert len(client.get("/api/v1/auth/project-memberships", headers=auth).json()) == 2
        # Project grants are captured in the short-lived access token.
        approver_auth = _login(client, "approver@example.test", "Secure-Approver1!")

        issued = _post(
            client,
            "/api/v1/auth/api-tokens",
            auth,
            {
                "name": "phase2-readonly",
                "permissions": ["project:read", "asset:read"],
                "project_ids": [project_id],
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        assert issued["token"].startswith("axt_")
        token_auth = {"Authorization": f"Bearer {issued['token']}"}
        assert client.get(f"/api/v1/projects/{project_id}", headers=token_auth).status_code == 200
        listed_tokens = client.get("/api/v1/auth/api-tokens", headers=auth).json()
        assert "token" not in listed_tokens[0]

        evidence = _post(
            client,
            "/api/v1/evidence",
            auth,
            {
                "project_id": project_id,
                "asset_id": asset_id,
                "evidence_type": "health_check",
                "title": "真实健康检查",
                "summary": "API 与数据库检查通过",
                "source_type": "agent",
                "source_ref": "agent://phase2-linux/health/1",
                "content_hash": "a" * 64,
                "classification": "internal",
                "gxp_classification": "non_gxp",
                "observed_at": datetime.now(UTC).isoformat(),
                "metadata": {"status": "healthy"},
            },
        )
        evidence_id = evidence["id"]
        assert client.get(f"/api/v1/evidence/{evidence_id}", headers=auth).status_code == 200

        incident = _post(
            client,
            "/api/v1/incidents",
            auth,
            {
                "project_id": project_id,
                "title": "Phase 2 incident",
                "description": "真实证据驱动的故障记录",
                "severity": "critical",
                "owner_id": admin_id,
                "participant_ids": [approver["id"]],
                "asset_ids": [asset_id],
                "evidence_ids": [evidence_id],
                "impact_scope": {"service": "api"},
            },
        )
        incident_id = incident["id"]
        _post(
            client,
            f"/api/v1/incidents/{incident_id}/timeline",
            auth,
            {
                "occurred_at": datetime.now(UTC).isoformat(),
                "entry_type": "evidence",
                "title": "健康证据已确认",
                "evidence_ids": [evidence_id],
            },
        )
        for status in ("acknowledged", "investigating", "resolved"):
            response = client.patch(
                f"/api/v1/incidents/{incident_id}", headers=auth, json={"status": status}
            )
            assert response.status_code == 200, response.text
        close_without_review = client.patch(
            f"/api/v1/incidents/{incident_id}", headers=auth, json={"status": "closed"}
        )
        assert close_without_review.status_code == 409
        draft_review = _put(
            client,
            f"/api/v1/incidents/{incident_id}/postmortem",
            auth,
            {
                "status": "draft",
                "summary": "服务恢复",
                "root_cause": "配置漂移",
                "action_items": [{"owner": "SRE", "action": "配置校验"}],
                "evidence_ids": [evidence_id],
            },
        )
        assert draft_review["created_by"] == admin_id
        approved_review = _put(
            client,
            f"/api/v1/incidents/{incident_id}/postmortem",
            approver_auth,
            {
                "status": "approved",
                "summary": "服务恢复",
                "root_cause": "配置漂移",
                "action_items": [{"owner": "SRE", "action": "配置校验"}],
                "evidence_ids": [evidence_id],
            },
        )
        assert approved_review["approved_by"] == approver["id"]
        assert (
            client.patch(
                f"/api/v1/incidents/{incident_id}", headers=auth, json={"status": "closed"}
            ).status_code
            == 200
        )

        now = datetime.now(UTC)
        change = _post(
            client,
            "/api/v1/changes",
            auth,
            {
                "project_id": project_id,
                "title": "受控服务变更",
                "description": "R2 单人审批变更",
                "change_type": "normal",
                "risk_level": "R2",
                "affected_asset_ids": [asset_id],
                "incident_ids": [incident_id],
                "evidence_ids": [evidence_id],
                "precheck_plan": [{"step": "检查服务"}],
                "implementation_plan": [{"step": "执行已注册动作"}],
                "validation_plan": [{"step": "验证服务"}],
                "success_criteria": [{"condition": "健康"}],
                "rollback_plan": [{"step": "恢复配置"}],
                "scheduled_start": (now - timedelta(minutes=5)).isoformat(),
                "scheduled_end": (now + timedelta(minutes=30)).isoformat(),
            },
        )
        change_id = change["id"]
        assert (
            _post(client, f"/api/v1/changes/{change_id}/submit", auth, {})["status"]
            == "pending_approval"
        )
        self_approval = client.post(
            f"/api/v1/changes/{change_id}/decisions",
            headers=auth,
            json={"decision": "approved", "comment": "self"},
        )
        assert self_approval.status_code == 403
        assert (
            _post(
                client,
                f"/api/v1/changes/{change_id}/decisions",
                approver_auth,
                {"decision": "approved", "comment": "CAB approved"},
            )["status"]
            == "approved"
        )
        for status in ("scheduled", "in_progress", "validating", "completed"):
            assert (
                _post(client, f"/api/v1/changes/{change_id}/status", auth, {"status": status})[
                    "status"
                ]
                == status
            )
        assert len(client.get(f"/api/v1/changes/{change_id}", headers=auth).json()["timeline"]) >= 6

        content = "当 API 不可用时，先验证数据库连接和最近变更。"
        document = _post(
            client,
            "/api/v1/knowledge/documents",
            auth,
            {
                "project_id": project_id,
                "title": "API 故障 SOP",
                "document_type": "sop",
                "source_type": "manual",
                "source_ref": "sop://api/availability/v1",
                "mime_type": "text/plain",
                "content_hash": sha256(content.encode()).hexdigest(),
                "classification": "internal",
                "gxp_classification": "non_gxp",
                "allowed_role_names": [],
                "tags": ["api"],
            },
        )
        bad_chunk = client.post(
            f"/api/v1/knowledge/documents/{document['id']}/chunks",
            headers=auth,
            json={
                "chunk_index": 0,
                "content": content,
                "content_hash": "0" * 64,
                "token_count": 20,
            },
        )
        assert bad_chunk.status_code == 422
        _post(
            client,
            f"/api/v1/knowledge/documents/{document['id']}/chunks",
            auth,
            {
                "chunk_index": 0,
                "heading": "处置步骤",
                "content": content,
                "content_hash": sha256(content.encode()).hexdigest(),
                "token_count": 20,
                "evidence_refs": [evidence["evidence_id"]],
            },
        )
        search = client.get("/api/v1/knowledge/search", headers=auth, params={"q": "数据库连接"})
        assert search.status_code == 200 and search.json()["total"] == 1
        vector_unavailable = client.post(
            "/api/v1/knowledge/search/vector",
            headers=auth,
            json={"project_id": project_id, "embedding": [0.0] * 1536},
        )
        assert vector_unavailable.status_code == 503

        finding_payload = {
            "project_id": project_id,
            "asset_id": asset_id,
            "source": "trivy",
            "external_id": "CVE-2026-0001:phase2",
            "category": "container_vulnerability",
            "title": "依赖组件存在高危漏洞",
            "description": "由扫描器归一化导入",
            "severity": "high",
            "cve_ids": ["CVE-2026-0001"],
            "evidence_ids": [evidence_id],
            "first_seen_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "vulnerability": {"cvss_score": 8.1, "affected_component": "example-lib"},
            "remediation": {"recommendation": "升级到修复版本"},
            "risk": {"likelihood": 4, "impact": 5},
            "ticket": {"system": "internal", "external_id": "SEC-1"},
        }
        finding = _post(client, "/api/v1/security/findings", auth, finding_payload)
        finding_id = finding["id"]
        detail = client.get(f"/api/v1/security/findings/{finding_id}", headers=auth).json()
        assert detail["risk"]["score"] == 20 and detail["vulnerability"]["cvss_score"] == 8.1
        accepted = client.patch(
            f"/api/v1/security/findings/{finding_id}/status",
            headers=auth,
            json={"status": "accepted", "reason": "隔离环境临时风险接受"},
        )
        assert accepted.status_code == 200
        assert (
            client.get(f"/api/v1/security/findings/{finding_id}", headers=auth).json()["risk"][
                "accepted"
            ]
            is True
        )

        slo = _post(
            client,
            "/api/v1/reliability/slos",
            auth,
            {
                "project_id": project_id,
                "name": "API Availability",
                "service_ref": "service://api",
                "sli_type": "availability",
                "prometheus_query": "avg(up{job='api'})",
                "target": 0.999,
                "warning_burn_rate": 1,
                "critical_burn_rate": 2,
            },
        )
        evaluation = _post(client, f"/api/v1/reliability/slos/{slo['id']}/evaluate", auth, {})
        assert evaluation["indicator_value"] == 0.9995
        capacity = _post(
            client,
            "/api/v1/reliability/capacity/analyze",
            auth,
            {
                "project_id": project_id,
                "name": "API CPU",
                "resource_type": "cpu",
                "service_ref": "service://api",
                "prometheus_query": "avg(cpu_percent)",
                "lookback_hours": 2,
                "forecast_hours": 2,
                "warning_threshold": 75,
                "critical_threshold": 90,
            },
        )
        assert capacity["result"]["sample_count"] == 3

        report = _post(
            client,
            "/api/v1/reports/generate",
            auth,
            {
                "project_id": project_id,
                "report_type": "incident_postmortem",
                "source_id": incident_id,
                "title": "Phase 2 故障复盘",
                "format": "json",
            },
        )
        download = client.get(f"/api/v1/reports/{report['id']}/content", headers=auth)
        assert download.status_code == 200
        assert sha256(download.content).hexdigest() == report["content_hash"]
        topology = client.get("/api/v1/topology", headers=auth, params={"project_id": project_id})
        assert topology.status_code == 200
        assert any(node["id"] == asset_id for node in topology.json()["nodes"])

        assert (
            client.delete(f"/api/v1/auth/api-tokens/{issued['id']}", headers=auth).status_code
            == 204
        )
        assert client.get(f"/api/v1/projects/{project_id}", headers=token_auth).status_code == 401
        assert (
            client.delete(
                f"/api/v1/auth/project-memberships/{membership['id']}", headers=auth
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/api/v1/auth/project-memberships/{operator_membership['id']}", headers=auth
            ).status_code
            == 204
        )
        audit = client.get("/api/v1/audit-logs", headers=auth, params={"page_size": 100})
        assert audit.status_code == 200
        actions = {item["action"] for item in audit.json()["items"]}
        assert {
            "identity.api_token.used",
            "incident.postmortem.updated",
            "change.approval.decided",
            "knowledge.search.performed",
            "security.finding.status.updated",
            "report.downloaded",
        }.issubset(actions)
        integrity = client.get("/api/v1/audit-logs/integrity", headers=auth)
        assert integrity.status_code == 200
        assert integrity.json()["valid"] is True
        assert integrity.json()["checked_entries"] >= len(actions)

    await engine.dispose()


def _bootstrap_and_login(client: TestClient) -> dict[str, object]:
    bootstrap = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Token": "change-me-development-bootstrap-token"},
        json={
            "tenant_name": "Phase Two Tenant",
            "tenant_slug": "phase-two-tenant",
            "email": "admin@example.test",
            "display_name": "Platform Admin",
            "password": "Secure-Admin1!",
        },
    )
    assert bootstrap.status_code == 201, bootstrap.text
    return {
        "user_id": bootstrap.json()["id"],
        "auth": _login(client, "admin@example.test", "Secure-Admin1!"),
    }


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "phase-two-tenant", "email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(
    client: TestClient, path: str, auth: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    response = client.post(path, headers=auth, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()


def _put(
    client: TestClient, path: str, auth: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    response = client.put(path, headers=auth, json=payload)
    assert response.status_code == 200, response.text
    return response.json()
