# Phase 2 发现纵向切片复审

> 复审时间：2026-08-13 20:20（Asia/Shanghai）
> 前序分数：Phase 1 59/100
> 边界：代码、迁移、开发级自检；未扫描真实网段，未部署测试环境

# NOT READY FOR TESTING

## 本切片已实现

- 建立发现任务、执行记录和候选资产三类有归属的数据实体，迁移头推进到 `0016`。
- 真实后端仅执行有界 RFC1918 IPv4 TCP connect；不使用随机结果、固定成功响应或生产假数据。
- 观测证据带 schema 版本、时间、端口、job/run 标识；候选以稳定指纹增量校准。
- 候选与 CMDB 分离，必须人工确认；关联现有资产时要求同项目且候选 IP 精确匹配。
- 创建的新资产保持未配置监控状态，避免“发现成功”等同于“监控成功”。
- 网络 I/O 在数据库事务外执行，失败只持久化脱敏错误码并写审计。

## 开发级验证

- Ruff format/check：168 个 Python 文件通过。
- mypy strict：156 个源文件通过。
- pytest：41 passed；覆盖率 81.17%，达到 80% 开发门槛。
- 发现 E2E：公网拒绝、私网任务、真实 observation 合同、候选隔离、人工确认、CMDB 创建、
  审计链均通过。测试替换的是网络边界端口，不把替身结果当真实设备运行证据。
- PostgreSQL 15：最小 0015 父结构上执行 `0016 upgrade → 0015 downgrade → 0016
  re-upgrade` 通过；3 表和候选 PK/Unique/FK 约束存在。

## 评分

| 维度 | Phase 1 | 当前 | 依据 |
|---|---:|---:|---|
| Product Completeness | 3 | 4 | 自动发现不再 MISSING，但仅完成私网 TCP 候选链 |
| Database | 7 | 8 | 发现任务/运行/候选及关键外键、唯一约束落地 |
| Data Integrity | 7 | 8 | 观测证据、稳定指纹、人工确认与同项目同 IP 约束 |
| 其他 13 维 | 78 | 78 | 未把 UI、专项监控、规则、厂商能力冒充完成 |

合计 **98/160，折算 61/100**。

Architecture、Backend、API、Database 已达到当前开发门槛；Overall、Frontend、Monitoring、
Alerting、Data Integrity 仍不达准入要求。Phase 2 还不是完整的数据管线阶段，因此不得进入
正式测试或部署。
