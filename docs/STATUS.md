# 项目状态

更新时间：2026-08-13 19:10（Asia/Shanghai）

## 当前结论

# NOT READY FOR TESTING

2026-08-13 全面体检基线为 **51/100**，低于 80 分总门槛，且 Architecture、Frontend、
Backend、API、Database、Monitoring、Alerting、Data Integrity 未达到强制最低分。当前禁止
进入正式全量测试和新一轮测试环境部署。基线报告见
`docs/audits/2026-08-13-current-project-health-report.md`。

历史 M1、M2、Enterprise 和 First E2E 证据仅说明旧脚本定义范围内曾执行；其中旧 First
E2E 通过“任意 node target 为 UP + 手工注入告警”形成假阳性，不能作为当前测试准入或完整
业务链通过证据。测试环境当前仍是旧 release `20260813T074459Z`、迁移
`0014_security_center`；本轮文件修改尚未部署，运行态没有生效。

## 当前整改阶段

Phase 0 — Emergency Fix 正在进行，尚未完成：

- 新增迁移 `0015_monitor_target_binding`，以 `MonitorTarget` 和
  `AssetMonitorBinding` 建立租户/项目/资产与 Prometheus job/instance 的唯一绑定。
- 新增 `/api/v1/monitoring/targets` 管理/验证 API 和
  `/api/v1/monitoring/assets/{asset_id}/node-metrics` 指标 API。未绑定、非唯一、过期或身份
  标签不匹配时明确失败，不再返回其他目标数据。
- Alertmanager 接入现在同时校验数据库绑定、实时 Prometheus 唯一目标、样本新鲜度和完整
  身份标签；证据查询结果也必须匹配同一绑定。
- Web 指标页切换资产或请求失败前清除旧指标，并展示样本时间、年龄和已验证数据源。
- Dashboard 已移除静态“业务闭环完成”声明，只展示真实依赖状态并明确不代表测试准入。
- First E2E 已改为只接受指定、已加载且健康的真实 Prometheus 规则；脚本不再手工注入
  Alertmanager 告警，并要求真实触发、身份匹配、规则恢复和事件恢复。

Phase 0 仍有以下阻断项：

- Git 仓库的敏感信息/大文件/生成物清查已通过；由于外部卷不支持 Git index 的原子
  rename，受控初始提交正在本机无元数据快照生成，尚未回写并复验 HEAD。
- 测试环境 Edge Agent Prometheus target 的 `connection refused` 尚未整改和现场验证。
- `0015` 尚未在真实 PostgreSQL 克隆上执行升级/回退/模型差异检查。
- 本轮尚未执行完整仓库质量门禁、Compose/Promtool、正式 E2E 或任何部署。

## 本轮已执行的开发级自检

- Ruff format/check（179 个 Python 文件）：通过。
- mypy strict（150 个源文件）：通过。
- pytest：`37 passed`；覆盖率 **82.35%**，达到当前开发门槛 80%。
- Web：Vitest `2 passed`；Vue/TypeScript typecheck、ESLint、Prettier 和 production build
  均通过。
- Go：gofmt、go vet、race test 和 Edge Agent build 通过。
- Compose：使用 `.env.example` 的静态 `config --quiet` 通过；本机 Docker daemon 未运行，
  未执行容器构建或运行态测试。
- Python `py_compile`：First E2E、monitoring、operations 与 `0015` 迁移通过。
- npm 隔离安装审计：0 vulnerabilities；Vite 仍提示已有大 chunk 警告，留待前端专项整改。

外部卷会生成 AppleDouble `._*` 文件并使 Ruff 缓存原子 rename 失败；本轮仅清理被
`.gitignore`/`.dockerignore` 排除的 macOS 元数据，并在 `/private/tmp` 无元数据副本执行
测试。没有删除源码、Secret 或运行数据。

## 文件状态与运行态边界

- 上述能力目前只是工作区代码/迁移/文档变更，并不代表测试环境已具备 `0015` 或新 API。
- OIDC 测试环境仍未启用，模型服务仍未配置，Prometheus 规则组仍为空；不得显示为通过。
- 厂商设备协议适配、发现/采集、规则中心、完整告警生命周期和 AIOps L1-L2 仍属后续阶段。
- GxP 资产继续禁止自动修复；R2+ 必须经过配置审批，AI 只可给证据化建议而不能执行。

## 下一步

1. 完成 P0 仓库敏感信息/大文件/生成物清查，建立可审计 Git 初始基线。
2. 修复 Edge Agent 的实际 Prometheus scrape 链，并补充真实 PostgreSQL `0014→0015` 验证。
3. 完成 Phase 0 复评分；若仍未达到总分和各强制维度门槛，继续 Phase 1，不进入正式测试或部署。
