# 备份与恢复

仓库已实现并测试备份、隔离恢复和 DR 证据入口；授权 Compose 测试环境已验证发布前
PostgreSQL custom-format 备份可读取。真实生产跨故障域恢复仍需在目标基础设施执行并签署
实际 RPO/RTO，不能由本地脚本测试替代。

- PostgreSQL：每日全量 + WAL/PITR，备份加密并跨故障域保存。
- MinIO：启用版本控制、对象锁和跨站复制；报告/附件单独生命周期。
- NATS JetStream：业务事实必须可从 PostgreSQL/Outbox 重放；关键 Stream 仍做快照。
- Vault：按产品官方流程备份存储后端和恢复密钥，分权保管。
- 配置：Helm values 的非敏感部分进 Git，Secret 只存 Secret Provider。

恢复顺序为 Secret Provider、PostgreSQL、NATS/Redis、MinIO、API/Worker、AI/Web，随后执行数据一致性和真实闭环验证。每季度至少做一次隔离恢复演练并记录 RPO/RTO。

## 可执行入口

- `scripts/backup/backup-production.sh` 使用受保护的 `PGSERVICEFILE` 生成 custom-format 数据库备份、schema、对象清单和 SHA-256；不会把连接密码写到参数或报告。
- `scripts/backup/restore-production.sh` 只允许恢复到名称以 `_restore` 或 `_dr` 结尾的空数据库，拒绝清理或覆盖现有数据库。
- `scripts/backup/dr-exercise.sh` 在隔离恢复后读取 Alembic head、租户数和审计数，并生成含 RTO 的只读证据文件。

MinIO 生产桶必须开启版本控制、对象锁和跨站复制；Vault 使用平台支持的 snapshot/auto-unseal 流程。数据库脚本不声称替代这两类外部系统的原生灾备能力。
