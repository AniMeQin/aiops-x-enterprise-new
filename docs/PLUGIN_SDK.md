# 插件 SDK 规范

插件必须提供符合 `packages/contracts/plugins/v1/plugin-manifest.schema.json` 的 Manifest，并通过独立适配层运行。核心领域不得导入特定厂商 SDK。

## 能力接口

- `DiscoveryPlugin.discover(context) -> DiscoveryResult`
- `CollectorPlugin.collect(context) -> TelemetryResult`
- `HealthCheckPlugin.check(context) -> HealthCheckResult`
- `ActionPlugin.precheck/execute/postcheck/rollback(context)`
- `QueryPlugin.query(context) -> QueryResult`
- `NotificationPlugin.send(context) -> NotificationResult`

所有结果必须包含成功标记、状态、开始/结束时间、证据、错误码、脱敏错误、是否可重试、原始输出引用、脱敏输出和元数据。插件不得返回无法追踪的纯文本。

## 安全要求

- 插件拥有独立身份和最小权限。
- 配置存 schema 校验后的非敏感参数，凭据只存引用。
- 执行动作遵守 R0-R4 风险、审批、维护窗口、超时、输出限制和回滚策略。
- 插件输出先脱敏，再进入事件、AI 或审计管道。
