# EVAL-019 稳定性门禁

本轮用仓库已有的四条控制面路径做有界长跑：导入状态机 100 次、PostgreSQL 临时 Reindex 队列 1000 行、SSE Registry 100 条流、Provider Gateway 100 次调用。故障全部在本地注入，避免真实外部调用。

- 导入：10 次 transient timeout 都在同一租约状态机内恢复，最终 100/100 完成。
- Reindex：4 个批次进入 retry_wait，恢复后 checkpoint 到 1000/1000；临时 PostgreSQL 表关闭连接后消失。
- SSE：每条流在 sequence=2 断开后恢复，200 个尾部事件重放，无重复或乱序。
- Provider：4 次网络失败经有界重试恢复，100 次成功，最终没有打开的 circuit。

这是稳定性回归证据，不是生产容量或真实厂商 SLA 承诺；发布前仍需批准的长时间 staging soak。
