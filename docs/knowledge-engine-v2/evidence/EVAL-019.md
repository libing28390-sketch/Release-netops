# EVAL-019 Evidence

## Task ID

EVAL-019 — 长时间运行导入、Reindex、SSE、Provider 故障和恢复稳定性测试。

- 状态：PASS
- 执行日期：2026-08-17

## 目标与边界

- 对真实导入状态机、SSE Stream Registry、LLM Gateway 和 PostgreSQL 临时 Reindex 队列执行有界长跑。
- 100 个导入周期、1000 行 Reindex 队列、100 个 SSE stream、100 个 Provider 周期均在 180 秒预算内完成。
- Provider 只做故障注入，不访问外部厂商；不连接设备、不执行设备写命令。
- SQLite 禁止；持久化夹具只使用 PostgreSQL 临时表。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-019-STABILITY-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval019_stability.py`
- `tests/knowledge_engine_v2/test_eval019_stability.py`
- `docs/knowledge-engine-v2/eval/eval-stability-v1.json`
- `docs/walkthrough/20260817_eval019_stability.md`

## 执行命令与结果

1. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe scripts\\knowledge_engine_v2_eval019_stability.py` — **PASS**，总耗时 2.842 秒，PostgreSQL 临时队列 rollback + connection close。
2. `$env:PYTHONPATH='backend'; .venv\\Scripts\\pytest.exe tests\\knowledge_engine_v2\\test_eval019_stability.py -q -p no:cacheprovider` — **3 passed**。
3. 相关导入/SSE/Provider 回归（`test_ingestion_pipeline_state_machine.py`、`test_ingestion_job_control_surface.py`、`test_api006_sse_contract.py`、`test_api007_sse_idempotency.py`、`test_llm_001_037_multi_provider.py`、`test_provider_auth_failure_surface.py`）— **35 passed**；未加载 SQLite conftest。
4. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe scripts\\knowledge_engine_v2_v1_baseline_pg.py` — **PASS**；PostgreSQL 10/10，retrieval_accuracy=1.0，citation_accuracy=1.0，wrong_vendor_rate=0，version_conflict_rate=0，`production_database_write=false`，`rollback=transaction_rollback`。
5. PostgreSQL 只读清理探针：`public.eval019_reindex_queue` 为 `NULL` — PASS。
6. `py_compile`、`npm.cmd run lint`、`npm.cmd run build`、`git diff --check` — PASS；build 仅有既有大 chunk warning。

## 关键输出

| 路径 | 样本 | 故障注入 | 恢复结果 |
| --- | ---: | ---: | --- |
| 导入 | 100 cycles | 10 次 transient timeout | 100 completed，terminal_failures=0，duplicate_idempotency=0 |
| Reindex | 1000 rows / 20 batches | 4 个 batch 转 retry_wait | completed=1000，max_checkpoint=1000，retry_rows=200 |
| SSE | 100 streams / 400 events | 每个 stream 在 sequence=2 后断开 | replayed=200，duplicate_events=0，out_of_order=0 |
| Provider | 100 logical calls / 104 attempts | 4 次 transient network failure | successes=100，circuit_open_after_recovery=false |

## 数据库影响

- Reindex 状态只写入 PostgreSQL 临时表 `eval019_reindex_queue`，没有永久表、索引或业务行写入。
- 事务 rollback 和连接关闭后，公共 schema 中不存在 `eval019_reindex_queue`。
- SQLite 未参与任何验收。

## 安全影响

- Provider 故障为本地 fake adapter 注入；`external_provider_request=false`。
- 报告只记录计数、状态和稳定错误边界，不记录 API Key、DSN、原始 Provider body、消息正文或设备凭据。
- SSE 恢复校验 tenant/user/fingerprint 绑定，禁止跨作用域重放。

## 回滚方式

- 无生产 schema/data 回滚动作；丢弃报告即可。
- 临时 PostgreSQL 事务 rollback，连接关闭负责清理临时对象。
- 代码回滚：回滚 EVAL-019 合同、脚本、测试、报告和证据提交。

## 已知限制

- 这是 180 秒内的有界本地稳定性门禁，不替代多小时生产级 soak 或真实 Provider SLA 测试。
- 外部 Provider 和设备写操作必须在批准窗口另行验证，本任务不执行。

## 最终结论

**PASS** — 导入、Reindex、SSE、Provider 故障注入与恢复全部完成；PostgreSQL/V1、租户边界、序列幂等、熔断恢复、清理和质量门禁均通过。
