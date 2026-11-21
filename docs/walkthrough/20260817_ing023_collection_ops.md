# ING-023 采集运行控制交付

## 本次实现

- Seed 批量采集增加服务端并发上限 `1..4`，默认 2；同租户同 Host 仍使用并发安全的固定间隔限速。
- CAT-004 safe outbound 增加显式、可注入的指数退避；仅对既有策略允许的 5xx 重试生效，单次最多 5 秒且受源超时约束。
- 对 `robots_policy` 执行三种明确行为：`not_applicable` 直接记录、`ignore_with_review` 记录人工复核标志、`respect` 通过 CAT-004 获取同 Host `/robots.txt` 并对注册 URL 执行 allow/disallow 判定。
- 官方批量采集开启运行策略时记录条款复核状态、robots 状态、稳定错误码和字节数；不记录正文、响应头、凭据或异常文本。
- 新增租户作用域 `kb_site_anomaly_alert` 投影，按 `tenant_id + host + alert_code` 幂等合并站点异常。没有复用无租户列的旧 `alert_events`。

## 失败与恢复

- robots 缺失按标准 `not_found_allow` 处理；robots 超时、解析失败或不允许访问时 fail-closed，不执行正文采集。
- 条款状态不是 `approved`、`waived` 或 `not_required` 时返回 `TERMS_REVIEW_REQUIRED`。
- 单条采集失败不会中断其它条目；达到严重信号或同 Host 同错误码阈值时写入站点告警。
- 回滚只需停用新增批量策略/路由；告警证据保留，不删除源版本、V1 文档或审计记录。

## 验证

- `test_ing023_collection_ops.py` + `test_ing022_official_seed_batch.py`：9 passed；
- `scripts/knowledge_engine_v2_ing023_pg_probe.py`：PostgreSQL PASS（JSONB、tenant/host/code 幂等合并、rollback）；
- 重点覆盖 robots allow/deny/404、5xx 退避、并发上限、站点告警租户键和迁移幂等。
