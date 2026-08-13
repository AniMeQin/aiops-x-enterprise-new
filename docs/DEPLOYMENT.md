# 部署指南

## 开发环境

```bash
cp .env.example .env
# 修改本地占位密码
sh scripts/generate-agent-pki.sh deploy/pki 127.0.0.1
docker compose --env-file .env config
docker compose --env-file .env up -d --build
docker compose --env-file .env ps
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS http://127.0.0.1:8001/api/v1/ai/status
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3000/api/health
```

首次构建会下载并编译固定版本的 pgvector。若 Docker Desktop 曾因宿主磁盘不足而卡在 `Created`，先释放空间并确认最小容器可以真正进入 Running，再执行 Compose 验收；不能只依据镜像构建成功判断平台已启动。

Agent 出站网关默认仅绑定 `127.0.0.1:8443`；测试环境如需远程 Agent，将 `AIOPS_AGENT_BIND` 设为明确管理网 IP，PKI SAN 必须与 Agent 访问地址一致。不要将 CA 私钥、任务签名私钥或一次性注册令牌提交到 Git。

控制面默认签发 24 小时 Agent 证书，续期窗口为到期前 8 小时；Agent 默认在到期前 6 小时开始轮换。对应变量为 `AIOPS_AGENT_CERTIFICATE_TTL_HOURS`、`AIOPS_AGENT_CERTIFICATE_RENEWAL_WINDOW_HOURS` 和 `AIOPS_CERTIFICATE_RENEW_BEFORE`。服务端窗口必须大于 Agent 的提前量。续期字段始于迁移 `0008_agent_certificate_renewal`，当前完整平台启动前必须确认数据库已到 `0014_security_center`。

Compose 镜像均使用固定标签；生产仍应固定到 digest、启用镜像签名和漏洞门禁。

## 生产环境

生产目标为 Kubernetes + Helm。仓库已交付 Helm、NetworkPolicy、External Secrets、迁移
Job、备份 CronJob、production fail-closed values 校验和供应链工作流，但尚未在用户提供的
生产 Kubernetes 集群完成环境证明。生产发布前仍须联调外部 PostgreSQL/Redis/NATS/
MinIO/Vault、OIDC、TLS、Pod Security、资源配额、HPA/PDB、备份恢复和镜像签名身份。

不要把当前开发 Compose 直接用于生产。

## 授权测试环境

测试环境使用不可变 release、共享配置/PKI、迁移前数据库备份、原子 `current` 指针和显式回滚。完整操作顺序、dry run、预检和 M1/M2 门禁见 [测试环境发布与 M1/M2 验收手册](deployment/TEST_ENVIRONMENT_RUNBOOK.md)。发布脚本默认不执行任何远程连接；必须在授权测试机上显式传入 `--apply` 才会修改运行态。
