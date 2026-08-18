from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_profile_edge_agent_metrics_are_reachable_only_on_the_compose_network() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    prometheus = (ROOT / "deploy/monitoring/prometheus.yml").read_text(encoding="utf-8")

    assert "AIOPS_AGENT_LISTEN: 0.0.0.0:9188" in compose
    assert 'targets: ["edge-agent:9188"]' in prometheus
    assert "9188:9188" not in compose


def test_prometheus_uses_worker_published_file_sd_targets() -> None:
    prometheus = (ROOT / "deploy/monitoring/prometheus.yml").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "/etc/prometheus/targets/node/*.json" in prometheus
    assert "refresh_interval: 15s" in prometheus
    assert "AIOPS_PROMETHEUS_TARGET_FILE_PATH" in compose
    assert "prometheus-target-init" in compose
    assert "prometheus-targets:/etc/prometheus/targets/node:ro" in compose
