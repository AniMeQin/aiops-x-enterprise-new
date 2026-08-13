# 项目状态

更新时间：2026-08-13 20:20（Asia/Shanghai）

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

Phase 1 — Architecture 的代码整改已完成开发级复审：

- 业务模块跨域直接 ORM import 已降为 0；CMDB、Tenant、Agent、Operations、Automation
  通过发布的 View/Scope、application 和 contracts 协作。
- 新增架构依赖测试，阻止未来 Router/Application 重新直接导入其他领域 Model。
- AI Gateway 的事件证据与状态写入归还 Operations 所有；Automation/Agent 的状态与事件
  时间线写入分别经拥有者接口完成。
- 所有 OpenAPI operation 全局声明统一 `ErrorResponse`，业务路由版本前缀由测试约束。
- Phase 1 复评分为 59/100，Architecture 7、API 8 达到该维度开发门槛；总分及其他强制
  维度仍不达标，正式测试/部署继续冻结。

Phase 2 — Data Pipeline 当前完成了“发现候选纵向切片”，但整个 Phase 尚未完成：

- 新增 `discovery_jobs`、`discovery_runs`、`discovery_candidates` 及迁移 `0016`；所有记录均
  受租户、项目和外键约束。
- 实现有界的 RFC1918 IPv4 TCP connect 发现：最多 256 主机、16 端口，网络 I/O 不占用
  数据库事务；不接收公网网段，不保存密码，也不伪造设备识别结果。
- 每条候选保存 `discovery.observation.v1` 证据和稳定指纹；重复运行增量更新，未再次观测的
  pending 候选标记 stale，已确认资产不会被自动退役。
- 候选必须由有权限的管理员显式确认，才可关联同项目同 IP 的现有 Asset 或创建新 Asset；
  新资产保持 `monitoring_status=not_configured`，不会被冒充为已监控。
- 开发 E2E 使用可记录的发现端口替身验证编排和数据状态，未执行真实网段扫描；真实后端是
  `AsyncTcpDiscoveryBackend`，不存在固定成功响应。
- 本切片复评分为 61/100；Phase 2 仍缺设备/接口/服务/容器/数据库实体、发现调度和
  候选→唯一监控绑定控制器，正式测试/部署继续冻结。

Phase 0 仍有以下阻断项：

- Git 仓库的敏感信息/大文件/生成物清查已通过；已从同一内容的本机无元数据快照建立
  受控初始提交 `bec5a9617f4cadb4d6f17eb06b4dba91367e42c8`，回写后 HEAD 可解析、
  378 个文件受跟踪、worktree clean、`git fsck --full` 无损坏。历史测试环境旧 release
  早于该提交，仍无法映射为此 commit。
- 测试环境 Edge Agent Prometheus target 的 `connection refused` 尚未整改和现场验证。
- `0015` 已在一次性 PostgreSQL 15 的最小 0014 父表基线上完成 upgrade → downgrade →
  re-upgrade；两个表、3 个唯一约束、版本号和回退删除均符合预期。完整旧库克隆升级和
  `alembic check` 仍属于正式数据库门禁，尚未执行。
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
- PostgreSQL 15 最小 `0014→0015→0014→0015`：通过，服务日志无 ERROR/FATAL/PANIC。
- PostgreSQL 15 最小 `0015→0016→0015→0016`：通过，3 张发现表可创建/回退，候选表 8 个
  PK/Unique/FK 约束符合预期；因本机无 pgvector，这不等于完整 `0001→0016` 历史链。
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

1. 继续 Phase 2，补齐 Device/Interface/Service/Container/Database Instance、采集状态和
   候选确认后受控建立唯一监控绑定；再进行完整 Phase 2 复审。
2. 只有未来准入允许部署后，才在测试环境复验 Edge Agent Prometheus target、真实规则触发
   与恢复；文件修复不等于运行态生效。
3. 正式数据库阶段补做完整旧库克隆升级、`alembic check`、备份恢复和回退兼容性验证。
