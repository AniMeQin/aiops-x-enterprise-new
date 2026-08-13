# 假设与待确认事项

记录日期：2026-08-13。

1. 旧 M1、M2、Enterprise 和 First E2E 证据仅代表旧脚本范围。2026-08-13 体检确认整体
   仍为 NOT READY FOR TESTING；旧 First E2E 未证明指定资产由真实规则触发，不能作为
   当前准入证据。
2. 第一阶段单区域部署，后续生产拓扑再确认多活或灾备区域。
3. 默认开发端口：Web 8080、API 8000、AI Engine 8001、MinIO Console 9001、NATS 8222。
4. 本地开发可使用 `.env` 中的开发凭据；生产必须由 Secret Provider 注入并禁止示例值。
5. 测试环境先使用本地 Bootstrap 管理员，密码不写入仓库；生产 OIDC 提供商、租户配额、数据保留期和 SLO 尚待业务/合规确认。
6. GxP 资产默认关闭自动修复；R2+ 需审批，R4 默认禁止。
7. Prometheus、Alertmanager、Grafana、Loki、Tempo、OTel 和 Vault 已纳入默认 Compose；
   运行状态以 `docs/STATUS.md` 的当次真实证据为准。
8. API 和事件字段采用英文 `snake_case`，中文仅用于 UI 和用户可读错误。
9. PostgreSQL 为唯一业务事实源；Redis/NATS 可重建，原始遥测由专用后端保存。
10. 当前开发基础镜像固定到显式标签；生产还要固定 digest 并做签名/漏洞验证。
11. 正式工作区位于会生成 AppleDouble 元数据的外部卷；质量检查可在不含 Secret、依赖和
    `._*` 的 `/private/tmp` 快照执行，但结果必须记录快照来源，不能冒充部署运行态。
12. 默认 Compose 的 node_exporter 只代表 Compose 宿主机，不得自动视为任意 CMDB 资产。
    环境规则和指标必须使用已验证 `AssetMonitorBinding`；无唯一绑定时按未配置处理。
