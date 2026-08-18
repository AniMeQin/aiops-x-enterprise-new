from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.cmdb.contracts import AssetView
from aiops_x_api.modules.monitoring.contracts import MetricSample, MetricsBackend, MetricSeries
from aiops_x_api.modules.monitoring.infrastructure.models import (
    AssetMonitorBinding,
    CollectorState,
    MonitorTarget,
)


@dataclass(frozen=True)
class VerifiedTarget:
    target: MonitorTarget
    binding: AssetMonitorBinding
    up_sample: MetricSample
    verified_at: datetime


def validate_target_instance(instance: str, asset: AssetView) -> None:
    try:
        parsed = urlsplit("//" + instance)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        host, port = None, None
    allowed_hosts = {value.lower() for value in asset.ip_addresses}
    if asset.hostname:
        allowed_hosts.add(asset.hostname.lower().rstrip("."))
    if (
        host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or host.lower().rstrip(".") not in allowed_hosts
    ):
        raise ApplicationError(
            code="AIOPS_5215",
            message="Prometheus 目标必须是资产登记的 IP 或主机名及显式端口",
            status_code=422,
        )


async def record_collector_result(
    session: AsyncSession,
    *,
    target: MonitorTarget,
    binding: AssetMonitorBinding,
    checked_at: datetime,
    sample_at: datetime | None,
    healthy: bool,
    error_code: str | None,
) -> CollectorState:
    state = await session.scalar(
        select(CollectorState).where(
            CollectorState.asset_id == binding.asset_id,
            CollectorState.collector_type == target.target_type,
        )
    )
    if state is None:
        state = CollectorState(
            tenant_id=binding.tenant_id,
            project_id=binding.project_id,
            asset_id=binding.asset_id,
            monitor_target_id=target.id,
            collector_type=target.target_type,
            status="unknown",
            config_revision=1,
            consecutive_failures=0,
        )
        session.add(state)
    state.monitor_target_id = target.id
    state.last_attempt_at = checked_at
    state.last_sample_at = sample_at
    state.last_error_code = error_code
    if healthy:
        state.status = "healthy"
        state.last_success_at = checked_at
        state.consecutive_failures = 0
    else:
        state.status = "failed"
        state.consecutive_failures += 1
    await session.flush()
    return state


def target_selector(target: MonitorTarget, binding: AssetMonitorBinding) -> str:
    values = {
        "job": target.prometheus_job,
        "instance": target.prometheus_instance,
        "aiops_tenant_slug": target.tenant_slug,
        "aiops_project_slug": target.project_slug,
        binding.identity_label: binding.identity_value,
    }
    encoded = ",".join(f'{key}="{_escape_label(value)}"' for key, value in values.items())
    return "{" + encoded + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


async def get_binding_for_asset(
    session: AsyncSession, *, tenant_id: UUID, asset_id: UUID
) -> tuple[AssetView, MonitorTarget, AssetMonitorBinding]:
    asset = await get_asset_for_scope(session, tenant_id=tenant_id, asset_id=asset_id)
    row = (
        await session.execute(
            select(MonitorTarget, AssetMonitorBinding)
            .join(
                AssetMonitorBinding,
                AssetMonitorBinding.monitor_target_id == MonitorTarget.id,
            )
            .where(
                AssetMonitorBinding.tenant_id == tenant_id,
                AssetMonitorBinding.asset_id == asset.id,
                AssetMonitorBinding.purpose == "node_metrics",
                AssetMonitorBinding.enabled.is_(True),
                MonitorTarget.enabled.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise ApplicationError(
            code="AIOPS_5204",
            message="资产尚未绑定已启用的监控目标",
            status_code=409,
            details={"asset_id": str(asset.id), "status": "not_configured"},
        )
    target, binding = row
    return asset, target, binding


async def verify_target(
    backend: MetricsBackend,
    *,
    target: MonitorTarget,
    binding: AssetMonitorBinding,
    now: datetime | None = None,
) -> VerifiedTarget:
    checked_at = now or datetime.now(UTC)
    samples = await backend.instant_query("up" + target_selector(target, binding))
    if len(samples) != 1:
        raise ApplicationError(
            code="AIOPS_5205",
            message="监控目标身份无法唯一验证",
            status_code=409,
            details={"matching_samples": len(samples)},
        )
    sample = samples[0]
    require_sample_identity(sample, target, binding)
    require_sample_freshness(sample, now=checked_at)

    return VerifiedTarget(
        target=target,
        binding=binding,
        up_sample=sample,
        verified_at=checked_at,
    )


def require_sample_freshness(sample: MetricSample, *, now: datetime | None = None) -> None:
    checked_at = now or datetime.now(UTC)
    age_seconds = max(0.0, (checked_at - sample.observed_at).total_seconds())
    if age_seconds > get_settings().monitoring_sample_max_age_seconds:
        raise ApplicationError(
            code="AIOPS_5206",
            message="监控目标样本已过期",
            status_code=409,
            details={"age_seconds": round(age_seconds, 3)},
        )


def require_sample_identity(
    sample: MetricSample, target: MonitorTarget, binding: AssetMonitorBinding
) -> None:
    expected = {
        "job": target.prometheus_job,
        "instance": target.prometheus_instance,
        "aiops_tenant_slug": target.tenant_slug,
        "aiops_project_slug": target.project_slug,
        binding.identity_label: binding.identity_value,
    }
    mismatches = sorted(key for key, value in expected.items() if sample.metric.get(key) != value)
    if mismatches:
        raise ApplicationError(
            code="AIOPS_5207",
            message="监控样本身份标签与资产绑定不一致",
            status_code=409,
            details={"mismatched_labels": mismatches},
        )


async def collect_node_metrics(
    backend: MetricsBackend,
    *,
    target: MonitorTarget,
    binding: AssetMonitorBinding,
    now: datetime | None = None,
) -> tuple[VerifiedTarget, dict[str, list[MetricSample]]]:
    verified = await verify_target(backend, target=target, binding=binding, now=now)
    queries = node_metric_queries(target, binding)
    samples = {"up": [verified.up_sample]}
    for name, query in queries.items():
        if name == "up":
            continue
        values = await backend.instant_query(query)
        if len(values) > 128:
            raise ApplicationError(
                code="AIOPS_5205",
                message="资产监控指标返回过多样本",
                status_code=409,
                details={"metric": name, "matching_samples": len(values)},
            )
        for value in values:
            require_sample_identity(value, target, binding)
            require_sample_freshness(value, now=verified.verified_at)
        samples[name] = values
    return verified, samples


def node_metric_queries(target: MonitorTarget, binding: AssetMonitorBinding) -> dict[str, str]:
    selector = target_selector(target, binding)
    identity_group = "job,instance,aiops_tenant_slug,aiops_project_slug," + binding.identity_label
    return {
        "up": "up" + selector,
        "cpu": (
            "100 - (avg by ("
            + identity_group
            + ") (rate(node_cpu_seconds_total"
            + _merge_selector(selector, {"mode": "idle"})
            + "[5m])) * 100)"
        ),
        "memory": (
            "(1 - (node_memory_MemAvailable_bytes"
            + selector
            + " / node_memory_MemTotal_bytes"
            + selector
            + ")) * 100"
        ),
        "filesystem": (
            "100 * (1 - node_filesystem_avail_bytes"
            + _merge_selector(
                selector, {"mountpoint": "/"}, negative_regex={"fstype": "tmpfs|overlay"}
            )
            + " / node_filesystem_size_bytes"
            + _merge_selector(
                selector, {"mountpoint": "/"}, negative_regex={"fstype": "tmpfs|overlay"}
            )
            + ")"
        ),
        "load1": "node_load1" + selector,
        "load5": "node_load5" + selector,
        "load15": "node_load15" + selector,
        "cpu_cores": "count by ("
        + identity_group
        + ") (count by (cpu,"
        + identity_group
        + ") (node_cpu_seconds_total"
        + selector
        + "))",
        "cpu_time": "sum by (mode,"
        + identity_group
        + ") (rate(node_cpu_seconds_total"
        + selector
        + "[5m]))",
        "memory_total_bytes": "node_memory_MemTotal_bytes" + selector,
        "memory_available_bytes": "node_memory_MemAvailable_bytes" + selector,
        "memory_cached_bytes": "node_memory_Cached_bytes" + selector,
        "swap_total_bytes": "node_memory_SwapTotal_bytes" + selector,
        "swap_free_bytes": "node_memory_SwapFree_bytes" + selector,
        "filesystem_inode_usage": "100 * (1 - node_filesystem_files_free"
        + selector
        + " / node_filesystem_files"
        + selector
        + ")",
        "disk_read_iops": "sum by (device,"
        + identity_group
        + ") (rate(node_disk_reads_completed_total"
        + selector
        + "[5m]))",
        "disk_write_iops": "sum by (device,"
        + identity_group
        + ") (rate(node_disk_writes_completed_total"
        + selector
        + "[5m]))",
        "disk_read_bytes": "sum by (device,"
        + identity_group
        + ") (rate(node_disk_read_bytes_total"
        + selector
        + "[5m]))",
        "disk_write_bytes": "sum by (device,"
        + identity_group
        + ") (rate(node_disk_written_bytes_total"
        + selector
        + "[5m]))",
        "network_receive_bytes": "sum by (device,"
        + identity_group
        + ") (rate(node_network_receive_bytes_total"
        + selector
        + "[5m]))",
        "network_transmit_bytes": "sum by (device,"
        + identity_group
        + ") (rate(node_network_transmit_bytes_total"
        + selector
        + "[5m]))",
        "network_receive_packets": "sum by (device,"
        + identity_group
        + ") (rate(node_network_receive_packets_total"
        + selector
        + "[5m]))",
        "network_transmit_packets": "sum by (device,"
        + identity_group
        + ") (rate(node_network_transmit_packets_total"
        + selector
        + "[5m]))",
        "network_errors": "sum by (device,"
        + identity_group
        + ") (rate(node_network_receive_errs_total"
        + selector
        + "[5m]) + rate(node_network_transmit_errs_total"
        + selector
        + "[5m]))",
        "network_drops": "sum by (device,"
        + identity_group
        + ") (rate(node_network_receive_drop_total"
        + selector
        + "[5m]) + rate(node_network_transmit_drop_total"
        + selector
        + "[5m]))",
        "uptime_seconds": "time() - node_boot_time_seconds" + selector,
        "processes_running": "node_procs_running" + selector,
        "processes_blocked": "node_procs_blocked" + selector,
        "tcp_connections": "node_sockstat_TCP_inuse" + selector,
    }


async def collect_node_metric_history(
    backend: MetricsBackend,
    *,
    target: MonitorTarget,
    binding: AssetMonitorBinding,
    metric: str,
    start: datetime,
    end: datetime,
    step_seconds: int,
) -> tuple[VerifiedTarget, list[MetricSeries]]:
    verified = await verify_target(backend, target=target, binding=binding)
    query = node_metric_queries(target, binding).get(metric)
    if query is None or metric == "up":
        raise ApplicationError(code="AIOPS_5212", message="不支持的历史指标", status_code=422)
    series = await backend.range_query(query, start=start, end=end, step_seconds=step_seconds)
    if len(series) > 128:
        raise ApplicationError(code="AIOPS_5205", message="历史指标返回过多序列", status_code=409)
    for item in series:
        require_metric_identity(item.metric, target, binding)
    return verified, series


def require_metric_identity(
    metric: dict[str, str], target: MonitorTarget, binding: AssetMonitorBinding
) -> None:
    sample = MetricSample(metric=metric, observed_at=datetime.now(UTC), value=0.0)
    require_sample_identity(sample, target, binding)


def build_alert_expression(
    *,
    metric_key: str,
    operator: str,
    threshold: float,
    tenant_slug: str,
    project_slug: str,
) -> str:
    selector = (
        '{job="node",aiops_tenant_slug="'
        + _escape_label(tenant_slug)
        + '",aiops_project_slug="'
        + _escape_label(project_slug)
        + '"}'
    )
    group = "job,instance,aiops_tenant_slug,aiops_project_slug,aiops_asset_id"
    values = {
        "host_down": "up" + selector,
        "cpu": (
            "100 - (avg by ("
            + group
            + ") (rate(node_cpu_seconds_total"
            + _merge_selector(selector, {"mode": "idle"})
            + "[5m])) * 100)"
        ),
        "memory": (
            "(1 - (node_memory_MemAvailable_bytes"
            + selector
            + " / node_memory_MemTotal_bytes"
            + selector
            + ")) * 100"
        ),
        "filesystem": (
            "100 * (1 - node_filesystem_avail_bytes"
            + _merge_selector(selector, {"mountpoint": "/"})
            + " / node_filesystem_size_bytes"
            + _merge_selector(selector, {"mountpoint": "/"})
            + ")"
        ),
    }
    expression = values.get(metric_key)
    if expression is None or operator not in {">", "<", "=="}:
        raise ApplicationError(code="AIOPS_5220", message="不支持的告警规则条件", status_code=422)
    return f"{expression} {operator} {threshold:g}"


async def require_alert_binding(
    session: AsyncSession,
    backend: MetricsBackend,
    *,
    asset: AssetView,
    labels: dict[str, str],
) -> VerifiedTarget:
    _, target, binding = await get_binding_for_asset(
        session, tenant_id=asset.tenant_id, asset_id=asset.id
    )
    if binding.verification_status != "verified":
        raise ApplicationError(
            code="AIOPS_5208",
            message="资产监控绑定尚未通过身份验证",
            status_code=409,
            details={"verification_status": binding.verification_status},
        )
    expected = {
        "job": target.prometheus_job,
        "instance": target.prometheus_instance,
        "aiops_tenant_slug": target.tenant_slug,
        "aiops_project_slug": target.project_slug,
        binding.identity_label: binding.identity_value,
    }
    mismatches = sorted(key for key, value in expected.items() if labels.get(key) != value)
    if mismatches:
        raise ApplicationError(
            code="AIOPS_5207",
            message="告警身份标签与资产监控绑定不一致",
            status_code=422,
            details={"mismatched_labels": mismatches},
        )
    return await verify_target(backend, target=target, binding=binding)


def _merge_selector(
    selector: str,
    equals: dict[str, str],
    *,
    negative_regex: dict[str, str] | None = None,
) -> str:
    parts = [selector[1:-1]] if selector[1:-1] else []
    parts.extend(f'{key}="{_escape_label(value)}"' for key, value in equals.items())
    parts.extend(
        f'{key}!~"{_escape_label(value)}"' for key, value in (negative_regex or {}).items()
    )
    return "{" + ",".join(parts) + "}"
