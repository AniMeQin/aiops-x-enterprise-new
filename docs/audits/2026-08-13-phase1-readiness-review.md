# Phase 1 架构整改复审

> 复审时间：2026-08-13 20:10（Asia/Shanghai）
> 前序分数：Phase 0 58/100
> 边界：代码、契约、架构测试与开发级回归；未部署测试环境

# NOT READY FOR TESTING

## 已完成整改

- 消除业务模块跨领域 `infrastructure.models` import，新增 AST 架构门禁；当前违规数 0。
- CMDB 发布不可变 `AssetView` 和受控资产状态写接口；Tenant 发布 Scope/解析接口。
- Monitoring 保持 `MetricsBackend` Protocol/Prometheus Adapter，不把 Prometheus 客户端耦合
  到核心业务。
- Agent/Automation/Operations 通过 contracts 处理在线 Agent、任务状态、维护窗、事件关联和
  时间线；AI Gateway 不再直接查询 Operations/Automation 表。
- FastAPI 全局 OpenAPI 声明统一、脱敏的 `ErrorResponse`；测试约束公开业务路由均在
  `/api/v1`。

## 验证

- Ruff：通过。
- mypy strict：154 个源文件通过。
- pytest：40 passed。
- 覆盖率：81.44%，高于 80%。
- 架构测试：跨域 ORM 违规 0；路由版本和 OpenAPI 错误 schema 通过。

## 评分变化

| 维度 | Phase 0 | Phase 1 | 依据 |
|---|---:|---:|---|
| Architecture | 6 | 7 | 发布接口、适配器端口和自动依赖门禁落地 |
| Backend | 6 | 7 | 跨域状态变更归还所有者；核心编排边界明确 |
| API | 7 | 8 | 统一错误 schema 和版本路由门禁 |
| 其他 13 维 | 74 | 74 | 本阶段未把产品/监控/告警/UX 等缺口冒充已完成 |

合计 **95/160，折算 59/100**。

Architecture 和 API 已达到强制维度最低分，Backend 达到 7；Overall、Frontend、Monitoring、
Alerting、Data Integrity 等仍未达标。项目进入 Phase 2 CMDB/Discovery 整改，不进入正式
测试或部署。
