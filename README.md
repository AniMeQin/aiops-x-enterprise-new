# AIOps-X Enterprise

AIOps-X Enterprise 是面向企业 IT 运维场景的智能运维控制平台。本仓库采用“模块化单体控制平面 + 独立数据平面 + 事件驱动”的 Monorepo 架构。

当前仓库具备 FastAPI 控制平面、Vue 3 管理台、Celery Worker、独立 AI Engine、Go Edge
Agent 和企业基础设施骨架，但 2026-08-13 全面体检结论为 **NOT READY FOR TESTING
(51/100)**。Phase 0 正在消除资产指标错绑、验收假阳性、错误完成声明和无版本基线等阻断
项；这不等于完整业务闭环或生产就绪。实时结论和文件/运行态边界以 `docs/STATUS.md` 为准。

测试环境交付使用 `make release` 生成不含 Secret/PKI/依赖的校验归档；安全预检、数据库备份、原子发布、失败恢复以及“先 M1、再 M2、最后企业全功能”的操作手册见 `docs/deployment/TEST_ENVIRONMENT_RUNBOOK.md`。

## 快速开始

前置条件：Docker Desktop、Python 3.12+、Node.js 22+、Go 1.24+、GNU Make。

```bash
make setup
make check
make up
```

启动后：

- 管理台：http://localhost:8080
- API 文档：http://localhost:8000/docs
- API 健康检查：http://localhost:8000/health
- AI Engine 状态：http://localhost:8001/api/v1/ai/status
- MinIO Console：http://localhost:9001
- NATS 监控：http://localhost:8222
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000

`make setup` 只会在不存在时由 `.env.example` 创建本地 `.env`，并在缺少时生成仅限本地开发的 Agent PKI。示例值和开发 PKI 不得用于生产，生产环境必须由 Secret Manager/受控 CA 注入。

如项目位于会生成 AppleDouble 元数据的 NAS/WebDAV 挂载盘，Docker 构建前可执行 `find . -name '._*' -type f -delete`；该命令只清理本仓库的 macOS 元数据文件。

## 常用命令

```bash
make dev        # 前台启动一期核心 Compose 服务并输出日志
make test       # Python、Web、Go 单元测试
make lint       # Python、Web、Go 静态检查
make typecheck  # Python 与 TypeScript 类型检查
make build      # 构建三种语言产物
make config     # 校验 Compose 配置
make migrate    # 执行 Alembic 迁移
make seed-dev   # 幂等登记测试设备的历史证据，当前状态为未检查（不保存明文凭据）
make e2e        # 隔离本机真实 API 与浏览器 E2E
make coverage   # 核心后端模块覆盖率
                        # Web 格式检查已纳入 make lint/make check
make verify-m1-m2          # 固定先运行 M1，再运行 M2 本地专项门禁
make test-deployment-scripts # 隔离验证发布、失败恢复与代码回滚状态机
make release    # 生成不含 Secret/PKI/依赖的归档及 SHA-256
make up         # 启动 Compose
make down       # 停止 Compose
make logs       # 查看 Compose 日志
make check      # 完整基础质量门禁
```

详细说明见 [开发文档](docs/DEVELOPMENT.md)、[部署文档](docs/DEPLOYMENT.md) 和 [当前状态](docs/STATUS.md)。
