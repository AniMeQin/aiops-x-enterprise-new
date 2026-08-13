# 授权测试环境

更新时间：2026-08-12

## Kali SSH 测试设备

| 字段 | 当前值 |
| --- | --- |
| 资产外部 ID | `DEV-LINUX-10-1-12-96` |
| IP | `10.1.12.96` |
| SSH 端口 | `22` |
| SSH 用户 | `qyy` |
| 远端主机名 | `kali` |
| 系统 | `Linux 7.0.12+kali-amd64 x86_64` |
| GxP 分类 | `unclassified` |
| 环境 | `development` |
| 凭据引用 | `vault://kv/aiops-x/development/assets/kali-10-1-12-96/ssh` |

## 历史连接验证（非当前状态）

- 验证时间：`2026-08-12T04:08:02Z`
- TCP 22：连接成功。
- SSH 身份认证：成功。
- 已验证用户：`qyy`。
- 连接验证正常后，按用户授权进入项目基础部署。

当前用户已说明测试环境无法连接，以上仅为历史证据，不代表当前可达；平台 development seed 将其当前状态登记为 `not_checked`，默认 Prometheus 也不会把本机 node_exporter 指标归属到该资产。

本次提供的明文密码仅用于即时 SSH/sudo 认证，未写入仓库、平台数据库、开发 seed、文档、共享环境文件或发布归档。后续平台运行时只能通过 Secret Provider 解析 `credential_ref`。

## 已执行的基础部署

- 部署根目录：`/home/qyy/aiops-x`。
- 发布布局：`releases/<release-id>` 保存不可变源码快照，`shared/.env` 保存权限为 `0600` 的环境配置，`current` 为当前发布的原子软链接。
- 已安装并启用 Kali 官方软件源提供的 Docker Engine、Compose 和 Buildx。
- 已启动 PostgreSQL/pgvector、Redis、NATS JetStream、MinIO、API、Worker、AI Engine 和 Web。
- 对局域网仅暴露 Web `8080/tcp`；API `8000`、AI `8001`、NATS 监控 `8222`、MinIO Console `9001` 均只绑定 `127.0.0.1`。
- 原有 Greenbone/OpenVAS、主机 PostgreSQL、Mosquitto 和 GSAD 服务保持原状，未被覆盖。
- 未在测试机安装 AIOps-X Edge Agent，未执行漏洞扫描、自动修复或远程变更。

## 授权边界

本记录仅覆盖上述单一主机的 SSH 验证和 AIOps-X 项目基础部署，不代表其他主机、端口或网段获得授权。远端安装 Agent、执行巡检、漏洞扫描或配置变更仍需要对应范围的明确授权。
