import importlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse


def test_m1_persistence_uses_server_side_action_filter(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend("scripts/acceptance")
    module = importlib.import_module("m1_persistence")
    required = {"asset.created", "project.updated", "identity.user.created"}

    class FakeClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def request(self, method: str, path: str) -> SimpleNamespace:
            assert method == "GET"
            self.paths.append(path)
            action = parse_qs(urlparse(path).query)["action"][0]
            return SimpleNamespace(body={"items": [{"action": action}], "total": 1})

    client = FakeClient()
    assert module.find_missing_audit_actions(client, required) == []
    assert len(client.paths) == len(required)
    assert all("page_size=1&action=" in path for path in client.paths)
