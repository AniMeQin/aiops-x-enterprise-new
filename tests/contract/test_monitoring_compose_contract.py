from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_profile_edge_agent_metrics_are_reachable_only_on_the_compose_network() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    prometheus = (ROOT / "deploy/monitoring/prometheus.yml").read_text(encoding="utf-8")

    assert "AIOPS_AGENT_LISTEN: 0.0.0.0:9188" in compose
    assert 'targets: ["edge-agent:9188"]' in prometheus
    assert "9188:9188" not in compose
