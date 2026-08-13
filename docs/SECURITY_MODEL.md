# 安全模型

## 信任边界

浏览器、控制平面、Worker、AI Engine、Agent、基础设施和外部集成均使用独立身份。网络可达不等于授权；每次请求必须验证主体、租户、项目、资源范围和动作。

## 身份与会话

- 企业身份优先 OIDC/OAuth2；当前本地 Bootstrap 由独立 Token 保护，只在用户表为空时允许调用。
- 密码使用随机 salt 的 scrypt 哈希；访问令牌为短期 HMAC-SHA256 JWT，Refresh Token 只以 SHA-256 哈希存储、每次刷新旋转并检测重放。
- 登录失败锁定、Refresh/Logout CSRF、HttpOnly Cookie、安全响应头、Redis 固定窗口 API 限流和完整登录审计由后端强制；Redis 不可用时进程内保守降级。OIDC 已实现 Authorization Code + PKCE、JWKS 验签、组映射与状态校验，真实 IdP 参数由部署环境提供。
- 用户与角色变更、权限委派和账号停用由后端校验并审计；非 Bootstrap 管理员不能授予自己不具备的权限。
- 生产 OpenAPI 默认关闭或受管理网认证保护。

## 授权

RBAC 给出功能权限，ABAC 约束租户、项目、资产、GxP 分类、风险等级和维护窗口。前端隐藏按钮不构成授权。R2 默认单人审批，R3 要求审批、窗口、备份、回滚和验证，R4 默认禁止。

## 凭据

PostgreSQL 仅保存 `credential_ref`。Vault 或兼容 Secret Provider 保存密文并按 API、Worker、Agent、插件分别授权。日志、错误、审计元数据和模型输入必须脱敏。

## Agent

- 一次性注册令牌使用后作废；后续通信为 Agent 主动出站 mTLS。
- 任务有签名、有效期、幂等 ID、资产范围、并发/资源/输出上限。
- Agent 默认没有任意 Shell，只执行 Action Registry 中的固定动作。
- 当前已实现一次性令牌、Agent 本地生成私钥和 CSR、24 小时客户端证书、独立 mTLS 网关、签名任务和自动证书轮换。Agent 在请求续期前先以 `0600` 原子保存待启用私钥/CSR；控制面只在续期窗口内接受当前证书，并允许上一张证书在其原有效期内重试丢失响应。公开 Web 网关会主动清除客户端伪造的证书身份头。
- Action Registry 仅注册 R0 `system.disk_usage`，通过 Go `Statfs` 读取，不启动 Shell；参数、超时、过期时间和 64 KiB 输出上限由双端验证。

## AI

AI Engine 不持有 SSH、WinRM、Docker Socket、Kubernetes 或数据库执行权限。建议必须使用结构化 schema 和证据引用，经策略、授权、审批和 Runbook 匹配后才可由执行器执行。外部文档内容一律视为不可信数据而非指令。

## 审计

审计表追加写入，数据库触发器阻止普通 UPDATE/DELETE。生产还需独立审计写入身份、WORM/对象锁归档、校验链和定期复核。

## 当前显式风险

Integration 探测仅允许 HTTP(S) 且要求 `integration:write`，但生产还必须通过 egress NetworkPolicy、DNS/IP allowlist 和代理层阻断内网元数据端点，避免 SSRF 扩大。
