# 测试环境发布与 M1/M2 验收手册

目标主机为授权测试环境，默认部署根目录为 `/home/qyy/aiops-x`。本手册不保存 SSH 密码、Bootstrap Token、用户密码、私钥或其他 Secret。

## 发布安全边界

- `shared/.env`、`shared/pki`、`backups`、旧 release 和 Compose 命名卷不会被发布脚本覆盖或删除。
- 发布包必须同时携带独立 SHA-256 文件，文件名和 Release ID 必须一致；不接受路径穿越、多个顶层目录或校验和不匹配的包。
- 升级既有环境时，迁移前必须生成 PostgreSQL custom-format 备份，并在容器内通过 `pg_restore --list` 验证。
- 只有 Alembic 到达 `0014_security_center` 后才原子切换 `current`。
- 新服务启动或 smoke test 失败时先确认旧 release 能识别当前 Alembic head；只有 schema 兼容才恢复旧代码。若数据库已迁移而旧代码不认识新版本，保留新代码指针并尝试前向恢复，数据库始终不会自动降级。
- 正常发布包不包含 `.env`、PKI、私钥、依赖目录、缓存、测试报告或构建产物。
- 未完成现场检查前，不运行 `--apply`。

## 一、本地发布前门禁

在本机恢复工作区执行：

```bash
cd /Volumes/Codex/智能监控运维平台
make verify-m1-m2
make test-deployment-scripts
make release
```

`make verify-m1-m2` 固定先 M1 后 M2。`make release` 在 `dist/releases/` 生成：

```text
aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz
aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz.sha256
```

将这两个文件上传到测试机的独立 artifacts 目录。传输后先在测试机执行：

```bash
cd /home/qyy/aiops-x/artifacts
sha256sum -c aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz.sha256
```

## 二、只读预检

先将发布包解到独立的预检目录，不覆盖 `current`：

```bash
mkdir -p /home/qyy/aiops-x/incoming/<UTC_RELEASE_ID>
tar -xzf /home/qyy/aiops-x/artifacts/aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz \
  -C /home/qyy/aiops-x/incoming/<UTC_RELEASE_ID>
cd /home/qyy/aiops-x/incoming/<UTC_RELEASE_ID>/AIOps-X-Enterprise-local-recovery
```

既有环境如果还没有独立 Alertmanager Token 文件，先验证再创建；该命令不会打印 Token，也不会覆盖已有文件：

```bash
scripts/deployment/sync-alertmanager-token.sh --root /home/qyy/aiops-x
scripts/deployment/sync-alertmanager-token.sh --root /home/qyy/aiops-x --apply
```

仅当是全新环境且 `shared/.env` 尚不存在时，才使用初始化命令。既有环境禁止重新初始化：

```bash
scripts/deployment/initialize-test-environment.sh \
  --root /home/qyy/aiops-x \
  --server-address 10.1.12.96

scripts/deployment/initialize-test-environment.sh \
  --root /home/qyy/aiops-x \
  --server-address 10.1.12.96 \
  --apply
```

执行只读预检：

```bash
scripts/deployment/remote-preflight.sh \
  --root /home/qyy/aiops-x \
  --release-dir "$PWD" \
  --agent-server-name 10.1.12.96
```

必须全部满足：Docker/Compose 可用、磁盘不少于 10 GiB、`shared/.env` 权限不大于 `0600`、必填变量非空、无占位 Secret、Web/Agent 绑定地址和 CORS 正确、Alertmanager Token 文件为私有权限、已有 PKI 的证书链/密钥对/有效期/SAN 正确、Compose 解析 19 个服务定义。端口已监听只给出警告，需确认监听者是当前 AIOps-X release。

## 三、部署

先 dry run：

```bash
scripts/deployment/install-release.sh \
  --archive /home/qyy/aiops-x/artifacts/aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz \
  --checksum-file /home/qyy/aiops-x/artifacts/aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz.sha256 \
  --release-id <UTC_RELEASE_ID> \
  --agent-server-name 10.1.12.96 \
  --root /home/qyy/aiops-x
```

确认 dry run、只读预检和维护窗口无误后才执行：

```bash
scripts/deployment/install-release.sh \
  --archive /home/qyy/aiops-x/artifacts/aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz \
  --checksum-file /home/qyy/aiops-x/artifacts/aiops-x-enterprise-<UTC_RELEASE_ID>.tar.gz.sha256 \
  --release-id <UTC_RELEASE_ID> \
  --agent-server-name 10.1.12.96 \
  --root /home/qyy/aiops-x \
  --apply
```

脚本依次执行：

1. 校验归档文件名、SHA-256 和安全路径。
2. 解包到新的不可变 release，不覆盖旧 release。
3. 保留已有 PKI；只有完全没有 PKI 时才生成一次。
4. 记录旧 release、镜像和 Compose 状态。
5. 对既有 PostgreSQL 做 custom-format 备份并验证可读取。
6. 重新运行预检并构建新镜像。
7. 执行 `alembic upgrade head`，确认 `0014_security_center`。
8. 原子切换 `current`，启动 17 个常驻服务并等待 health；`alertmanager-init` 与
   `minio-init` 应成功退出。
9. 检查 API `/ready`、Web 入口和 Agent Gateway TLS/HTTP 405。
10. 将发布证据写到 `backups/<UTC_RELEASE_ID>/`，再把 release 设为只读。

## 四、先 M1，后 M2

发布脚本成功只说明基础运行态就绪，不等于里程碑验收通过。严格执行 [M1_M2_ACCEPTANCE.md](../M1_M2_ACCEPTANCE.md)：

1. 先验证 M1 身份、租户、项目、CMDB、RBAC、关系、审计和重启持久化。
2. M1 任一项失败立即停止，不启动 M2 Agent。
3. M1 全部通过后，再验证 M2 一次性 Token、真实 Go Agent、mTLS、心跳、签名 R0 任务、耐久账本和证书续期。
4. 每阶段保存真实请求、Request ID、资源 ID、审计动作、容器状态和新日志时间戳。

### M1 现场命令

以下命令只在测试机发布成功后执行。管理员密码和首次 Bootstrap Token 通过隐藏输入进入当前 shell，不写入命令行、脚本、证据或历史记录：

```bash
DEPLOYMENT_ROOT=/home/qyy/aiops-x
CURRENT_RELEASE=$(readlink -f "$DEPLOYMENT_ROOT/current")
RELEASE_ID=$(basename "$CURRENT_RELEASE")
EVIDENCE_DIR="$DEPLOYMENT_ROOT/backups/$RELEASE_ID/acceptance"
install -d -m 0700 "$EVIDENCE_DIR"

read -r -p 'M1 tenant slug: ' AIOPS_ACCEPTANCE_TENANT_SLUG
read -r -p 'M1 administrator email: ' AIOPS_ACCEPTANCE_ADMIN_EMAIL
export AIOPS_ACCEPTANCE_TENANT_SLUG AIOPS_ACCEPTANCE_ADMIN_EMAIL
read -r -s -p 'M1 administrator password: ' AIOPS_ACCEPTANCE_ADMIN_PASSWORD
printf '\n'
export AIOPS_ACCEPTANCE_ADMIN_PASSWORD
```

先读取 Bootstrap 状态。只有响应为 `{"required":true}` 时才隐藏输入部署配置中的 Bootstrap Token：

```bash
curl -fsS http://10.1.12.96:8080/api/v1/auth/bootstrap/status
read -r -s -p 'Bootstrap token when required: ' AIOPS_ACCEPTANCE_BOOTSTRAP_TOKEN
printf '\n'
export AIOPS_ACCEPTANCE_BOOTSTRAP_TOKEN
```

执行 M1 CRUD/RBAC/审计第一阶段；此时证据状态应为 `restart_required`，不能开始 M2：

```bash
python3 "$CURRENT_RELEASE/scripts/acceptance/m1_live.py" \
  --base-url http://10.1.12.96:8080 \
  --api-health-url http://127.0.0.1:8000 \
  --tenant-slug "$AIOPS_ACCEPTANCE_TENANT_SLUG" \
  --admin-email "$AIOPS_ACCEPTANCE_ADMIN_EMAIL" \
  --evidence-file "$EVIDENCE_DIR/m1-before-restart.json"
```

保存新日志时间戳后重启 API 与 Web，再验证健康和持久化：

```bash
export AIOPS_PKI_DIR="$DEPLOYMENT_ROOT/shared/pki"
export AIOPS_ALERTMANAGER_TOKEN_FILE="$DEPLOYMENT_ROOT/shared/alertmanager-webhook-token"
docker compose --project-directory "$CURRENT_RELEASE" \
  -f "$CURRENT_RELEASE/compose.yaml" \
  --env-file "$DEPLOYMENT_ROOT/shared/.env" \
  restart api web
curl --retry 30 --retry-delay 2 --retry-all-errors -fsS \
  http://127.0.0.1:8000/ready
curl --retry 30 --retry-delay 2 --retry-all-errors -fsS \
  http://10.1.12.96:8080/ >/dev/null
python3 "$CURRENT_RELEASE/scripts/acceptance/m1_persistence.py" \
  --prepared-evidence "$EVIDENCE_DIR/m1-before-restart.json" \
  --evidence-file "$EVIDENCE_DIR/m1-passed.json"
```

只有 `m1-passed.json` 为私有权限、`status` 为 `passed`，并完成人工 Web 页面抽查后，才继续 M2。

### M2 现场命令

M2 脚本强制读取通过的 M1 证据，构建并启动真实 Go Agent，在独立状态目录中验证一次性 Token 重放被拒绝、公共 Web 网关伪造 mTLS 头被拒绝、mTLS 心跳、真实 R0 磁盘任务、任务幂等、`0600` 身份/账本以及无 Token 重启：

```bash
python3 "$CURRENT_RELEASE/scripts/acceptance/m2_live.py" \
  --m1-evidence "$EVIDENCE_DIR/m1-passed.json" \
  --evidence-file "$EVIDENCE_DIR/m2-basic-live.json" \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --server-address 10.1.12.96
```

该脚本成功时只写 `basic_gate_passed`，不会误报完整 M2。随后执行自动故障注入补充验收：

```bash
python3 "$CURRENT_RELEASE/scripts/acceptance/m2_supplemental_live.py" \
  --m1-evidence "$EVIDENCE_DIR/m1-passed.json" \
  --m2-basic-evidence "$EVIDENCE_DIR/m2-basic-live.json" \
  --evidence-file "$EVIDENCE_DIR/m2-passed.json" \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --server-address 10.1.12.96
```

该脚本使用受控临时网关验证结果落账/恢复补发与续期丢包/同 CSR 恢复，完成后恢复默认
续期窗口并复查心跳。只有 `m2-passed.json` 为 `status=passed` 才能进入下一阶段。

M2 基础门禁通过后执行企业全功能现场闭环：

```bash
python3 "$CURRENT_RELEASE/scripts/acceptance/enterprise_live.py" \
  --m1-evidence "$EVIDENCE_DIR/m1-passed.json" \
  --m2-evidence "$EVIDENCE_DIR/m2-passed.json" \
  --evidence-file "$EVIDENCE_DIR/enterprise-live.json"
```

该入口创建独立测试资源，不执行生产自动修复；验证报告下载哈希、三个 Telemetry backend、
七个内置插件、独立审批人、R2 自审批拒绝和审计链完整性。仅 `status=passed` 可作为企业
闭环证据。Enterprise 通过后执行第一条完整实时业务链路：

```bash
python3 "$CURRENT_RELEASE/scripts/acceptance/first_e2e_live.py" \
  --m1-evidence "$EVIDENCE_DIR/m1-passed.json" \
  --m2-evidence "$EVIDENCE_DIR/m2-passed.json" \
  --evidence-file "$EVIDENCE_DIR/first-e2e-live.json" \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --alert-name '<已加载且绑定目标的规则名>' \
  --server-address 10.1.12.96
```

运行期间由授权操作人对指定监控目标制造并恢复规则定义的真实、可逆测试条件。脚本拒绝
空规则、重复规则、非唯一资产目标、过期/错标签样本和手工告警注入；随后验证
Alertmanager、Event、只读 Runbook、Agent 执行、恢复、时间线、AI 明确状态和审计记录。
仅 `status=passed` 可签字。

```bash
unset AIOPS_ACCEPTANCE_ADMIN_PASSWORD AIOPS_ACCEPTANCE_BOOTSTRAP_TOKEN
```

## 五、代码回退

先 dry run，并由负责人确认旧代码与当前数据库 schema 兼容：

```bash
scripts/deployment/rollback-release.sh \
  --root /home/qyy/aiops-x \
  --target-release-id <PREVIOUS_RELEASE_ID>
```

确认后执行：

```bash
scripts/deployment/rollback-release.sh \
  --root /home/qyy/aiops-x \
  --target-release-id <PREVIOUS_RELEASE_ID> \
  --apply
```

该命令只切换代码并重启服务，不删除 release、备份或命名卷，不自动恢复 PostgreSQL。若需要数据库恢复，应停止所有写入，保留故障现场，再使用发布前的 `postgres-before.dump` 建立独立恢复库验证；未经单独审批，不覆盖当前数据库。
