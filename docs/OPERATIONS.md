# 运维手册

## 探针

- API `/health`：仅进程存活，不访问依赖。
- API `/ready`：执行 PostgreSQL `SELECT 1`，失败返回 503。
- AI Engine `/ready`：服务进程就绪；模型可用性看 `/api/v1/ai/status`。
- Worker 8002 `/health`、`/ready`、`/metrics`：Celery 进程信号与真实 Redis `celery` 队列深度；仅容器网络访问。
- Edge Agent `/health`：本地进程存活；未注册时 `/ready` 返回 503 和 `registration_required`，本地身份损坏或证书过期分别返回 `certificate_invalid`、`certificate_expired`。证书默认提前 6 小时自动续期，成功日志只记录 Agent ID 和到期时间，不记录私钥或 CSR。
- Prometheus、Alertmanager 和 Grafana 由 Compose 使用镜像内原生命令做 health check。Loki/Tempo 的 distroless 镜像不含 shell/wget，Compose 只校验进程启动；运行验收必须从宿主或外部探针请求其 `/ready`。OTel Collector 提供仅回环暴露的 13133 health extension。

## 平台自身可观测性

- API、Worker、AI Engine 与 Agent 暴露 Prometheus `/metrics`。
- API 记录请求数/耗时、超过 1 秒的慢请求、异常请求、数据库池、Agent 在线数、告警接入和自动化任务指标。
- Worker 记录 Celery 队列深度与 Outbox 发布成功/失败/待处理数；AI Engine 记录调用耗时和 `completed`/`failed`/`not_configured` 结果。
- OTel gRPC 接收 API、SQLAlchemy、Redis、Celery 和 AI Engine Trace，转发到 Tempo；容器日志经 Collector 进入 Loki。
- 日志采用 JSON，并携带可用的 Request ID/Trace ID；不得记录 Token、Cookie、密码、私钥或完整连接字符串。

## 基础排障

```bash
docker compose --env-file .env ps
docker compose --env-file .env logs --tail=200 api worker ai-engine
docker compose --env-file .env exec postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
docker compose --env-file .env exec redis redis-cli -a "$REDIS_PASSWORD" ping
```

日志不得复制到公开渠道前不经脱敏。API Ready 失败先区分 DNS、端口、凭据、迁移和数据库资源耗尽，不以重复重启掩盖根因。

## 变更

所有生产变更先备份、记录变更单和回滚条件，分批发布并观察错误率、延迟、队列积压和数据库连接池。R2+ 业务动作遵守审批策略。
