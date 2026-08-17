# EVAL-018 PostgreSQL 性能样本

## 本轮完成

EVAL-018 使用真实 PostgreSQL 18.4，在临时会话中按 10k、100k、1m 行分别测量 FTS、pg_trgm 和 pgvector Top-K 查询，并记录 P50/P95/P99。每个路径五次重复，因此 P99 明确标注为最大观测值。

## 结果摘要

- FTS 三档 P95 均低于 1ms。
- pgvector 三档 P95 均低于 1ms，Top-K=10，租户泄漏为 0。
- pg_trgm 在 100k 为约 1.03s，1m 为 11.31s；1m 结果超过 3s 初始目标，形成容量告警。

## 处理原则

本结果不改写生产数据，也不把 SQLite 当作容量证据。1m trigram 的风险保留在报告中，后续发布前需要更窄的预过滤/阈值和 staging 语料复测，不能通过隐藏该告警来勾选发布门槛。
