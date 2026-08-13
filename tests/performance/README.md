# 性能与容量门禁

`k6-api.js` 对真实已登录 API 执行渐进式只读负载，默认 20 VU、5 分钟，门禁为错误率 `<1%`、P95 `<750ms`、P99 `<1500ms`。令牌仅通过进程环境传入，不进入脚本、报告或仓库。

```bash
AIOPS_BASE_URL=https://aiops.example.com \
AIOPS_ACCESS_TOKEN='从受控测试账户临时获取' \
k6 run tests/performance/k6-api.js
```

容量页使用真实 Prometheus range query 生成趋势；压测时同时记录 API/Worker CPU、内存、数据库连接池、Redis/Celery 队列、JetStream Consumer lag、告警接入延迟与任务成功率。环境未运行 k6 时不得声明性能门禁通过。
