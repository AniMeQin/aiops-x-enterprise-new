# 测试计划

## 统一门禁

- Python：Ruff、mypy strict、pytest 与 80% coverage。
- Web：ESLint、Prettier、Vue/TypeScript strict、Vitest、production build、Playwright 全页面。
- Go Agent：gofmt、go vet、golangci-lint、race test、build。
- 数据库：单线 Alembic revision、真实 PostgreSQL 旧库克隆升级/回退、`alembic check`。
- 部署：Compose、Helm default/production/backup/ExternalSecrets、发布状态机与回退保护。
- 安全供应链：依赖审计、SBOM、漏洞扫描、digest 和签名流程。
- 数据保护：PostgreSQL/MinIO 备份、校验、空目标恢复拒绝、DR 证据权限。

## 现场固定顺序

1. 部署前快照、旧库克隆升级验证、正式备份和 release 安装。
2. M1 live + API/Web 重启持久化；只接受 `status=passed`。
3. M2 live；脚本必须读取 M1 证据，验证真实 Go Agent、mTLS、R0 与耐久状态。
4. Enterprise live；脚本必须读取 M1/M2 证据，验证 Phase 2 与企业模块真实业务闭环。
5. First E2E；指定资产必须存在唯一监控绑定，由已加载 Prometheus 规则的真实条件变化触发
   并恢复，再验证 Alertmanager → Alert/Event → Runbook → Agent → Timeline/Audit。
6. 记录服务状态、Alembic head、Request ID、资源 ID、审计链与现场日志，不保存 Secret。

任一阶段失败立即停在该阶段，不运行后一阶段掩盖失败。外部 OIDC、模型、厂商接口、
Kubernetes、异地 DR 未提供真实环境时必须标记“未配置/未执行”，不能用固定成功响应。

最新实测结果与已知边界见 `docs/STATUS.md`；现场命令见
`docs/deployment/TEST_ENVIRONMENT_RUNBOOK.md`。
