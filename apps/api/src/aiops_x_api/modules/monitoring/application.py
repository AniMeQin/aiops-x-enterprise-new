from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.cmdb.application import get_asset_for_scope
from aiops_x_api.modules.cmdb.infrastructure.models import Asset
from aiops_x_api.modules.monitoring.contracts import MetricSample, MetricsBackend
from aiops_x_api.modules.monitoring.infrastructure.models import AssetMonitorBinding, MonitorTarget


@dataclass(frozen=True)
class VerifiedTarget:
    target: MonitorTarget
    binding: AssetMonitorBinding
    up_sample: MetricSample
    verified_at: datetime


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
) -> tuple[Asset, MonitorTarget, AssetMonitorBinding]:
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
    selector = target_selector(target, binding)
    identity_group = "job,instance,aiops_tenant_slug,aiops_project_slug," + binding.identity_label
    queries = {
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
    }
    samples = {"up": [verified.up_sample]}
    for name in ("cpu", "memory", "filesystem"):
        values = await backend.instant_query(queries[name])
        if len(values) > 1:
            raise ApplicationError(
                code="AIOPS_5205",
                message="资产监控指标返回多个候选样本",
                status_code=409,
                details={"metric": name, "matching_samples": len(values)},
            )
        for value in values:
            require_sample_identity(value, target, binding)
            require_sample_freshness(value, now=verified.verified_at)
        samples[name] = values
    return verified, samples


async def require_alert_binding(
    session: AsyncSession,
    backend: MetricsBackend,
    *,
    asset: Asset,
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
