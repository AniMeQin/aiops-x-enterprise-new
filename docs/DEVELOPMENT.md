# 开发指南

## 环境

- Python 3.12+ 与 uv
- Node.js 22+ 与 npm
- Go 1.24+
- Docker Desktop 与 Compose

```bash
make setup
make check
make e2e       # 隔离 SQLite + 真实 API + Vue 生产预览的本机浏览器测试
make coverage  # 输出核心模块真实覆盖率，不隐藏未达门禁
npm run format:check --workspace @aiops-x/web
```

API 本地启动：

```bash
uv run uvicorn aiops_x_api.main:app --app-dir apps/api/src --reload --port 8000
```

Web 本地启动：

```bash
npm run dev --workspace @aiops-x/web
```

## 变更规则

1. 领域功能放入对应模块，不跨模块直接查询表。
2. Schema 变化必须新增 Alembic 迁移并验证升级/降级策略。
3. 事件和插件变更要增加新契约版本或保持向后兼容。
4. Demo 数据仅放 `tests/fixtures` 或明确 development seed。
5. 完成后更新测试和 `docs/STATUS.md`。
