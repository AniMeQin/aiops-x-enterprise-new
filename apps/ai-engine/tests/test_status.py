from aiops_x_ai.main import (
    _analysis_schema,
    _chat_completions_request,
    _provider_output_text,
    app,
    provider_status,
)
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def test_unconfigured_ai_is_explicit(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("AIOPS_AI_PROVIDER", raising=False)
    monkeypatch.delenv("AIOPS_AI_API_KEY", raising=False)
    client = TestClient(app)
    response = client.get("/api/v1/ai/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "configured": False,
        "provider": None,
        "message": "AI 服务未配置",
    }
    analysis = client.post("/api/v1/ai/analyze", json={"evidence": {"event": {}}})
    assert analysis.status_code == 200
    assert analysis.json()["status"] == "not_configured"
    assert analysis.json()["hypotheses"] == []


def test_unsupported_provider_is_not_treated_as_configured(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_AI_PROVIDER", "unknown-vendor")
    monkeypatch.setenv("AIOPS_AI_API_KEY", "test-only-key")
    client = TestClient(app)

    status = client.get("/api/v1/ai/status")

    assert status.status_code == 200
    assert status.json()["status"] == "unsupported"
    assert status.json()["configured"] is False


def test_local_provider_does_not_require_a_fake_api_key(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_AI_PROVIDER", "local")
    monkeypatch.delenv("AIOPS_AI_API_KEY", raising=False)

    status = provider_status()

    assert status.configured is True
    assert status.provider == "local"


def test_chat_compatible_adapter_uses_strict_evidence_schema() -> None:
    request = _chat_completions_request(
        "local-model", "system", {"event": {"id": "evt-1"}}, _analysis_schema()
    )

    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["messages"][1]["content"] == '{"event":{"id":"evt-1"}}'
    assert (
        _provider_output_text(
            "local", {"choices": [{"message": {"content": '{"summary":"real"}'}}]}
        )
        == '{"summary":"real"}'
    )
