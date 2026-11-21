# OBS-007：Import/Reindex 队列与租约观测

## 目标

统一 Import 与 Reindex 的队列积压、失败和租约异常信号，并在 AI metrics
接口中提供有界告警条件。

## 验证路径

1. Import 控制面从状态机聚合 queued、retry_wait、running、failed 与过期租约。
2. Reindex 从 PostgreSQL 的 `ai_knowledge_reindex_job` 和 `scheduler_locks`
   聚合队列与运行中任务的缺失/过期锁。
3. 生命周期仅记录低基数事件名；API 不返回任务、租户、worker、SQL 或错误正文。
4. `GET /api/ai/metrics` 返回 `jobs.observability.queues`、`alerts` 和阈值。

## 告警规则

- backlog 达到 `AI_JOB_QUEUE_BACKLOG_ALERT_THRESHOLD`（默认 100）时为 warning；
- failed 达到 `AI_JOB_FAILURE_ALERT_THRESHOLD`（默认 1）时为 error；
- lease anomaly 达到 `AI_JOB_LEASE_ANOMALY_ALERT_THRESHOLD`（默认 1）时为 error。

这里只输出确定性的聚合条件，不绑定外部通知系统；部署层可将该响应接入现有
监控/值班渠道。
