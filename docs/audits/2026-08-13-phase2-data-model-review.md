# Phase 2 核心数据模型复审

> 复审时间：2026-08-13 20:30（Asia/Shanghai）
> 前序分数：发现切片 61/100
> 边界：工作区代码、迁移和开发级回归；未部署、未执行真实采集

# NOT READY FOR TESTING

## 本切片证据

- Asset 补齐 OS 版本、业务、发现来源/状态、最后连接与最后监控时间。
- AssetComponent 通过父子外键和类型约束表达接口、服务、容器、Kubernetes 工作负载、数据库
  实例；不存在无归属组件。
- CollectorState 对 Asset/collector type 和 MonitorTarget 都有唯一性，持久化连续失败、
  最后尝试/成功/样本时间和错误码。
- Prometheus 绑定验证及指标读取会更新 CollectorState 和 Asset monitoring status；失败不写
  成功时间，样本过期或身份错误继续 fail closed。

## 验证

- Ruff format/check：168 个 Python 文件通过。
- mypy strict：156 个源文件通过。
- pytest：41 passed；覆盖率 81.00%。
- 组件 API E2E：database instance、其下 container、列表与 CMDB 归属通过。
- Collector E2E：真实 MetricsBackend 合同样本驱动 healthy、last sample 与 Asset active 状态；
  stale/duplicate/wrong identity 仍失败。
- PostgreSQL 15 最小父结构：`0015→0017→0016→0017` 通过，2 表/6 列可逆，13 个关键约束。

## 评分

| 维度 | 前序 | 当前 | 依据 |
|---|---:|---:|---|
| Product Completeness | 4 | 5 | 组件库存从 MISSING 进入可用后端数据模型 |
| Monitoring | 5 | 6 | 采集状态、失败计数和样本时间成为持久事实 |
| Data Integrity | 8 | 9 | 组件归属、采集状态唯一性和状态同步有数据库约束 |
| 其他 13 维 | 81 | 81 | UI、专项采集、规则、厂商能力未冒充完成 |

合计 **101/160，折算 63/100**。Data Integrity 达到强制最低分；Overall、Frontend、
Monitoring、Alerting 仍不通过，继续冻结正式测试和部署。
