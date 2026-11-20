# OBS-005 Provider 运行监控

OBS-005 把 Provider 运行状态集中到两个已有接口:

- `/api/ai/metrics`：低延迟进程内视图，按 `provider_id:model_id` 给出请求量、成功/错误、错误率、平均/P95 延迟、Token、估算成本、限流和 Fallback 计数。
- `/api/ai/usage/summary`：PostgreSQL `ai_usage_daily` 权威汇总，给出日请求、成功/错误、错误率、平均延迟和估算成本，并保留旧表兼容查询。

限流事件包括 Provider 429、并发获取超时和熔断打开；Fallback 具备 started/success/error 三态。所有指标都不携带 Prompt、Provider 响应正文、凭据或原始异常文本。
