# 测试环境部署验收证据

> 历史证据：本页只记录 `20260812T051146Z` 当时的 8 服务发布，不代表当前本地 0008 代码已部署。当前部署状态以 `docs/STATUS.md` 为准。

验收日期：2026-08-12

## 环境与发布

- 主机：`10.1.12.96`，Kali GNU/Linux Rolling，x86_64，12 CPU、15 GiB RAM。
- 发布 ID：`20260812T051146Z`。
- 发布目录：`/home/qyy/aiops-x/releases/20260812T051146Z`。
- 当前入口：`/home/qyy/aiops-x/current`。
- 共享数据：Compose named volumes，不随发布目录切换；环境配置位于 `shared/.env`，权限 `0600`。
- 源码归档完整性由 `artifacts/20260812T051146Z.tar.gz.sha256` 独立记录。

## 健康和连通性

- `docker compose up -d --build --wait` 成功返回。
- `postgres`、`redis`、`nats`、`minio`、`api`、`worker`、`ai-engine`、`web` 共 8 个服务的显式健康检查全部为 `healthy`。
- `http://10.1.12.96:8080/` 返回 HTTP 200。
- `http://10.1.12.96:8080/api/v1/system/info` 返回 API 版本 `0.1.0`、环境 `development`、数据库 `connected`。
- 局域网直连 `10.1.12.96:8000` 被拒绝，证明 API 未脱离 Web 反向代理直接暴露。

## 数据与安全验证

- PostgreSQL 运行版本 16.4，`vector` 扩展版本 0.8.0。
- Alembic 当前版本 `0001_foundation`。
- 授权资产 `DEV-LINUX-10-1-12-96` 已登记，IP 为 `10.1.12.96`，当时基于真实 SSH 验证记录为 `reachable`，Agent 状态 `not_installed`。当前 seed 不再把历史连通性写成实时监控状态，默认保存为 `not_configured`。
- 资产仅保存 Secret Provider 引用，不保存明文 SSH 密码。
- 审计日志写入 `development.asset.created | success`；对已有记录的 UPDATE 被 `audit_logs is append-only` 触发器拒绝。
- 全栈重启前后，资产 UUID 与审计记录数保持一致，验证持久化正常。

## 质量门禁

- Python：Ruff 通过，mypy 31 个源文件通过，pytest 7/7 通过。
- Web：ESLint、vue-tsc、Vitest 1/1、Vite 生产构建通过。
- Edge Agent：gofmt、go vet、go test、go build 通过。
- 已知非阻断项：FastAPI TestClient 存在上游弃用警告；前端主 JS 产物约 1,049 kB，后续需路由级拆包。

## 回滚

1. 确认目标历史发布目录的 SHA-256 校验通过。
2. 将 `current` 原子切换到目标发布目录。
3. 在 `current` 中执行 `docker compose --env-file .env up -d --build --wait`。
4. 复查 8 个服务健康状态、Web/API 真实请求和数据持久化。

回滚不会自动降级数据库 schema。若未来发布含不兼容迁移，必须按该发布的备份/恢复手册单独处理。
