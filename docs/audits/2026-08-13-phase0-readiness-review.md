# Phase 0 测试准入复审

> 复审时间：2026-08-13 19:30（Asia/Shanghai）
> 基线报告：`docs/audits/2026-08-13-current-project-health-report.md`
> 边界：工作区代码/迁移/开发级自检；未部署测试环境，未执行正式系统测试

# NOT READY FOR TESTING

Phase 0 整改后暂定分数为 **58/100**，仍低于 80 分，Architecture、Frontend、Backend、
API、Monitoring、Alerting、Data Integrity 仍未达到强制最低分。正式全量测试和测试环境新
release 继续冻结。

## P0 处置结果

| ID | 工作区状态 | 开发证据 | 运行态证据 | 结论 |
|---|---|---|---|---|
| P0-01 资产/指标错绑 | `0015` 增加唯一 MonitorTarget/AssetMonitorBinding；指标和告警均实时校验唯一性、身份和新鲜度 | 后端回归、真实 PostgreSQL 15 迁移 upgrade/downgrade 通过 | 未部署；测试环境仍是 0014 | PARTIAL |
| P0-02 First E2E 假阳性 | 删除手工告警注入；要求唯一资产绑定、指定健康规则、真实触发与真实恢复 | 脚本编译、help gate、代码审查通过 | 规则仍为空，未执行 live E2E | PARTIAL |
| P0-03 错误完成声明 | Dashboard 移除静态闭环；README/Status/Roadmap/Data Model/验收文档同步为 NOT READY | Web typecheck/lint/test/build 和文档复读 | 旧测试环境 Web 尚未更新 | PARTIAL |
| P0-04 无 Git 基线 | 清查 378 个候选文件、约 2.4 MB；高置信 Secret 命中 0；建立本地初始 commit | HEAD `bec5a9617f4cadb4d6f17eb06b4dba91367e42c8`、378 tracked、worktree clean、fsck 无损坏 | 历史 release 早于此 commit，不能追溯映射 | IMPLEMENTED |
| P0-05 Agent scrape DOWN | Compose profile Agent 改为内部网络监听 `0.0.0.0:9188`，不发布宿主端口 | Compose contract、Go tests/build、Compose config 通过 | 测试环境 target 仍未复验 | PARTIAL |

## 开发级验证结果

- Ruff format/check：179 个 Python 文件通过。
- mypy strict：150 个源文件通过。
- pytest：37 passed；核心模块覆盖率 82.35%。
- Web：2 个 Vitest、TypeScript/Vue typecheck、ESLint、Prettier、production build 通过；
  Vite 保留已有大 chunk 警告。
- Go：gofmt、go vet、race test、Edge Agent build 通过。
- Compose：`.env.example` 静态 config 通过；本机 Docker daemon 未运行。
- PostgreSQL 15：最小 0014 父表基线执行 `0015 upgrade → 0014 downgrade → 0015
  re-upgrade` 通过；2 张表、3 个唯一约束和版本号符合预期，日志无 ERROR/FATAL/PANIC。
- 敏感信息清查：真实 `.env` 被忽略，PKI 私钥/Vault Token 候选不存在；私钥头、常见云
  Token、带凭据 URL 等高置信规则命中 0；无 >10 MB 候选文件。

这些是整改开发自检，不是正式测试环境验收。完整旧库克隆升级、Prometheus live target、
真实规则触发/恢复和旧 UI 替换均未发生。

## Phase 0 后评分

| 维度 | 基线 | 当前 | 变化依据 |
|---|---:|---:|---|
| Architecture | 5 | 6 | 新监控端口/适配器边界；全仓跨模块 ORM 和 Router 职责混合仍在 |
| Product Completeness | 3 | 3 | 未新增发现、设备专项监控、规则和厂商产品能力 |
| Frontend | 5 | 5 | 修复旧指标与错误声明；核心运维产品页仍缺失 |
| Backend | 6 | 6 | 监控校验增强；采集、发现和调度核心仍缺失 |
| API | 6 | 7 | 增加目标管理/验证/资产指标专用 API；错误合同仍未完整文档化 |
| Database | 6 | 7 | 增加监控目标/绑定实体与唯一约束；JSON/无 FK 债务仍在 |
| Monitoring | 3 | 5 | 数据身份/新鲜度闭合；仍只有 Linux 四项即时指标、无动态发现 |
| Alerting | 4 | 5 | 接入前实时绑定验证、First E2E 真实规则门禁；规则/生命周期仍缺 |
| Security | 8 | 8 | Secret 清查通过；动态 OIDC/MFA/轮换仍缺 |
| Observability | 6 | 6 | scrape 配置已修但未 live 验证；产品 UX 未扩展 |
| Reliability | 5 | 5 | 本轮未完成 HA/容量/故障实证 |
| Data Integrity | 4 | 7 | 资产-目标唯一绑定、样本新鲜度和假阳性门禁；跨域 JSON/FK 债务仍在 |
| UX | 4 | 4 | 文案和 stale state 修复；Dashboard/钻取/工作流仍不足 |
| Deployment | 7 | 7 | 新配置静态通过；未做新 release 或 runtime 验证 |
| Documentation | 5 | 7 | 状态、路线图、数据模型、验收手册与现实同步 |
| Automation | 4 | 4 | 本轮未扩展 Runbook/验证/回滚能力 |

合计 **92/160，折算 58/100**。

## 强制门槛

| 准入项 | 要求 | 当前 | 结果 |
|---|---:|---:|---|
| Overall | ≥80 | 58 | 不通过 |
| Architecture | ≥7 | 6 | 不通过 |
| Frontend | ≥7 | 5 | 不通过 |
| Backend | ≥7 | 6 | 不通过 |
| API | ≥8 | 7 | 不通过 |
| Database | ≥7 | 7 | 达到开发级门槛 |
| Monitoring | ≥8 | 5 | 不通过 |
| Alerting | ≥7 | 5 | 不通过 |
| Security | ≥8 | 8 | 达到静态门槛 |
| Data Integrity | ≥9 | 7 | 不通过 |

## 决策

Phase 0 的四个原始 P0 均已有实质代码或基线处置，但其中三项尚缺运行态证据。由于整体和
强制维度仍不达标，项目进入 Phase 1 架构整改；不得开始 Full System Test 或部署。
