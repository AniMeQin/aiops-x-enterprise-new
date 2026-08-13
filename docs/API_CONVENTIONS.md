# API 约定

- 正式业务 API 前缀为 `/api/v1`；`/health`、`/ready`、`/metrics` 是平台探针。
- JSON 字段使用 `snake_case`，时间为 UTC RFC 3339。
- 列表接口统一支持 `page`、`page_size`、显式排序和白名单筛选。
- 创建/任务类接口支持 `Idempotency-Key`；请求响应携带 `X-Request-ID`、`X-Trace-ID`。
- 租户和项目来自已验证的授权上下文，不信任客户端单独声明。
- 资产关系通过 `/api/v1/assets/{asset_id}/relations` 创建和查询；删除操作只写入 `expires_at` 使关系失效，保留拓扑证据历史。

错误格式：

```json
{
  "code": "AIOPS_1004",
  "message": "请求的资源不存在",
  "details": {},
  "request_id": "...",
  "trace_id": "..."
}
```

API 不返回堆栈、SQL、令牌、密码、本地路径、内部网络信息或未脱敏输出。错误码一旦公开只增加不复用。
