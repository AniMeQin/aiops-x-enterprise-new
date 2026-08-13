# M1 / M2 分阶段验收

## 固定顺序

测试环境发布后只按以下顺序执行：

1. 部署前备份与预检，执行数据库迁移并确认 Alembic 为当前受控 head。
2. 验收 M1“身份、租户与 CMDB”。
3. 只有 M1 全部通过，才开始 M2“Agent 注册与只读巡检”。
4. 任一阶段失败即停在该阶段，保留日志、请求 ID、数据库版本和容器状态，不用后一阶段的结果掩盖前一阶段失败。
5. M2 基础门禁通过后，执行断线补发与证书续期故障注入，只有生成完整 `m2-passed.json`
   才执行 Enterprise live；最后执行 First E2E。

本地专项门禁已拆分，可单独执行，也可使用强制串行入口：

```bash
make verify-m1
make verify-m2
make verify-m1-m2
```

`verify-m1-m2` 内部先调用 `verify-m1`，成功退出后才调用 `verify-m2`。

测试机自动化入口位于 `scripts/acceptance/`：

- `m1_live.py` 执行真实健康、Bootstrap/登录、Project、CMDB、关系生命周期、RBAC 和审计验证，只生成 `restart_required` 证据。
- 重启 API/Web 后，`m1_persistence.py` 复查项目、资产、关系历史、凭据脱敏和审计仍存在，才生成 `status=passed` 的 M1 证据。
- `m2_live.py` 拒绝读取未通过的 M1 证据，并运行真实 Go Agent 主流程；其证据状态固定为 `basic_gate_passed`。
- `m2_supplemental_live.py` 强制读取基础证据，自动验证结果上传断线落账/恢复补发，以及
  证书续期响应丢失后的同 CSR/上一张有效证书恢复；成功后才生成 `m2-passed.json`。
- `enterprise_live.py` 同时读取通过的 M1/M2 证据，验证企业身份、证据/复盘、R2 分离审批、知识、安全、SLO/容量、MinIO 报告、拓扑、插件、Telemetry 和审计哈希链。
- `first_e2e_live.py` 要求资产存在唯一且实时验证通过的监控绑定，并要求指定的已加载
  Prometheus 规则由真实监控条件触发和恢复；脚本不会手工注入告警。随后验证
  Alertmanager、Event、Runbook、真实 Agent、时间线、AI 明确状态和审计链。

准确现场命令及 Secret 隐藏输入方式见 [TEST_ENVIRONMENT_RUNBOOK.md](deployment/TEST_ENVIRONMENT_RUNBOOK.md)。

## M1 通过条件

- API、Web、PostgreSQL 和 Redis 健康，登录入口可访问。
- Bootstrap 状态与实际数据库一致；管理员可登录，`/api/v1/auth/me` 返回平台管理员角色。
- Project 可创建、读取和更新，幂等键不会产生重复项目。
- Linux 资产和应用资产可创建、读取和更新；凭据只显示“已配置”，响应不回显 `credential_ref` 或秘密值。
- `RUNS_ON` 关系可创建并从入站方向查询；逻辑失效后默认列表不可见，历史查询仍可追溯。
- 只读角色可以读取项目/资产，但创建项目返回 403。
- 审计中存在 Bootstrap、登录、项目、资产、关系、角色和用户动作；重启服务后项目、资产和审计仍存在。
- Web 的项目、资产列表、资产详情、用户/角色页面读取真实 API，无 Mock 成功状态。

M1 环境证据至少记录：发布时间、Alembic 版本、Compose 服务状态、M1 专项测试输出、一次真实登录、资产 UUID、关系 UUID、403 响应和对应审计动作。

`m1-before-restart.json` 不能作为 M1 通过证据；必须在真实 API/Web 重启后由 `m1_persistence.py` 生成 `m1-passed.json`，再人工抽查项目、资产详情和用户/角色页面。

## M2 前置条件

- M1 已签字通过。
- Agent Gateway 的证书 SAN 与 Agent 实际访问地址一致，8443 只开放到授权管理网。
- 控制面已配置 CA、任务签名证书和私钥；私钥文件未进入源码归档。
- 目标资产已在 M1 创建，且未绑定其他有效 Agent。

## M2 通过条件

- 平台为目标资产生成一次性注册 Token；首次注册成功，重放同一 Token 返回 401。
- Linux Go Agent 本地生成私钥和 CSR，`identity.json` 权限为 `0600`，私钥不出主机。
- 后续请求经过 mTLS；伪造证书身份头不能通过公开 Web 网关。
- Agent `/health` 返回 200，`/ready` 返回 200；平台显示 Agent online、主机名/版本/能力与真实上报一致。
- 平台下发 `system.disk_usage` R0 任务；Agent 验证 RSA-PSS 签名与过期时间后执行，回传经过限制的结构化结果，不存在任意 Shell 入口。
- 断开控制面后结果保存在 `task-ledger.json`，恢复连接后补发；同一任务不会重复执行。
- 证书进入续期窗口后，Agent 先将待续期私钥和 CSR 原子落盘，再请求新证书；新序列号生效并产生 `agent.certificate.renewed` 审计。
- 模拟第一次续期响应失败后，Agent 使用同一 CSR 重试；旧证书仅在其原到期时间前用于续期恢复，过期证书使 `/ready` 返回 503 `certificate_expired`。

默认续期参数为服务端 24 小时 TTL、提前 8 小时开放续期，Agent 提前 6 小时发起。若明日要在短时间内验证自动续期，可仅在隔离测试发布中使用 1 小时 TTL、1 小时服务端窗口和 `55m` Agent 提前量；验证后恢复默认值并重新签发测试 Agent，不能把加速参数带入生产基线。

M2 环境证据至少记录：Token ID（不记录 Token 明文）、Agent ID、注册前后 readiness、旧/新证书序列号、心跳时间、任务 ID、脱敏结果、断线补发日志、重复任务请求数和续期审计。只有这些运行证据齐全，才将 M2 标记为环境通过。

`m2_live.py` 覆盖主链路但不伪造耗时场景，因此只输出 `basic_gate_passed`。
`m2_supplemental_live.py` 使用受控故障网关真实执行两个补充场景，结束时恢复服务端续期
基线并复查心跳；只有该脚本输出 `status=passed` 才算完整 M2。
