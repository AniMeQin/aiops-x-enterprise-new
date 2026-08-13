# 路线图

路线图以 2026-08-13 全面体检和测试准入门槛为准。旧 M1/M2/Enterprise/First E2E 只保留为
历史范围证据，不再用“页面存在、容器健康、旧脚本通过”表示产品完成。

## Phase 0 — Emergency Fix（进行中）

消除资产/指标错绑、First E2E 假阳性、静态完成声明和无 Git 基线；修复实际 scrape 链并
建立可追溯 release→commit 证据。完成后重新评分。

## Phase 1 — Architecture（待开始）

收敛 Router/Application/Repository/Adapter 边界，停止跨模块直接访问表，建立发现、采集、
规则、厂商与模型接口及统一错误合同。

## Phase 2 — CMDB and Discovery（待开始）

实现监控实体、发现任务、候选资产、证据确认、接入监控与增量校准。

## Phase 3 — Monitoring（待开始）

补齐 Linux、网络、Windows、Docker、Kubernetes、数据库监控模型、采集链、产品页和数据
新鲜度/质量控制。

## Phase 4 — Alerting（待开始）

实现规则 CRUD、版本/发布/回滚、阈值与恢复条件、规则评估结果，以及认领、分派、备注、
解决、关闭、重开、通知升级和值班链。

## Phase 5 — Frontend（待开始）

建设真实 Dashboard、设备/服务监控视图、规则中心、集成/OIDC/模型配置 UI、跨模块钻取和
完整 loading/error/empty/permission 状态。

## Phase 6 — AIOps（待开始）

构造证据包、常用模型厂商适配、L1/L2 结构化建议、风险/验证/回滚方案；AI 不直接执行，
R2+ 与 GxP 继续服从审批策略。

## Phase 7 — Security and CI（待开始）

完成 Secret scanning、SAST/依赖/镜像/许可证门禁、权限矩阵、审计完整性和数据保护验证。

## Phase 8 — Full System Test（准入达标后）

仅在总分 ≥80 且所有强制维度达到最低分后，执行完整单元、集成、契约、E2E、故障、性能、
安全、升级回退、备份恢复测试。

## Phase 9 — Deployment（正式测试通过后）

验证真实环境的迁移、HA、External Secrets、TLS、滚动升级/回滚、监控、容量和 DR；文件已
修改与运行态已生效必须分别留证。
