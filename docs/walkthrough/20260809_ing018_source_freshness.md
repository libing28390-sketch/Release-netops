# ING-018 实现演练

## 目标

对已验证且启用采集的 Source Registry 定期发起条件 GET，请求携带最近一次
不可变 Source Version 的 ETag/Last-Modified。刷新不暴露正文，不覆盖旧版本事实。

## 运行路径

1. APScheduler 每 30 分钟执行 `knowledge_source_freshness_refresh`。
2. `source_freshness_service.refresh_sources` 以租户为边界、最多选择 100 个源。
3. `safe_outbound_http.safe_fetch` 重新执行 CAT-004 的 DNS、TLS、重定向和大小校验。
4. 304 写入 `not_modified` 观测；200 由 SHA-256 幂等边界分类为 `unchanged` 或 `changed`。
5. 所有结果写入 `kb_source_refresh_observation`；响应正文只在内存中用于计算哈希。

## 运维检查

```text
GET /api/knowledge-v2/sources/{source_id}/refresh-observations?limit=50
```

返回字段只包含租户内的 source/version ID、状态码、哈希、验证器和稳定错误码，
不包含正文、凭据、DSN 或异常原文。

## 回滚

停用调度任务并关闭刷新写入即可回滚运行行为；m0120 的观测和现有
`kb_source_version` 不删除、不重写。V1 `ai_document` 不受影响。

