# EVAL-018 Evidence

## Task ID

EVAL-018 — 执行 10k/100k/1m 性能样本并记录 P50/P95/P99。

- 状态：PASS_WITH_CAPACITY_WARNING

## 目标与边界

- 使用真实 PostgreSQL 18.4、`vector 0.8.6`、`pg_trgm 1.6`。
- 仅创建临时会话表 `eval018_chunk` 和临时索引；不写入 V1/V2 生产表，不执行生产 DDL。
- 代表 FTS、pg_trgm 和 pgvector tenant-scoped Top-K=10 路径；每个规模和路径执行 5 次，P99 按 nearest-rank 计算，样本量为 5 时 P99 是最大观测值。
- 性能评估不等同于生产语料分布或发布批准；超过初始 P95 目标的结果必须保留为容量告警。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-018-PERFORMANCE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval018_performance.py`
- `tests/knowledge_engine_v2/test_eval018_performance.py`
- `docs/knowledge-engine-v2/eval/eval-performance-v1.json`
- `docs/walkthrough/20260817_eval018_performance.md`

## 执行命令与结果

环境：`DATABASE_URL` 由项目 `.env` 读取；数据库权威为 PostgreSQL；SQLite 未参与验收。

1. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe -m py_compile scripts/knowledge_engine_v2_eval018_performance.py tests/knowledge_engine_v2/test_eval018_performance.py` — PASS。
2. `$env:PYTHONPATH='backend'; .venv\\Scripts\\pytest.exe tests/knowledge_engine_v2/test_eval018_performance.py -q -p no:cacheprovider` — **2 passed**。
3. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe scripts/knowledge_engine_v2_eval018_performance.py` — **PASS_WITH_CAPACITY_WARNING**；三档样本完整结束，结果写入 `docs/knowledge-engine-v2/eval/eval-performance-v1.json`。
4. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe scripts/knowledge_engine_v2_v1_baseline_pg.py` — **PASS**；10/10，retrieval_accuracy=1.0，citation_accuracy=1.0，wrong_vendor_rate=0，version_conflict_rate=0，`production_database_write=false`，`rollback=transaction_rollback`。
5. PostgreSQL 只读清理探针：`public.eval018_chunk` 与 `public.eval018_fts` 均为 `NULL` — PASS；临时对象已随连接关闭清理。
6. `npm.cmd run lint` — PASS；`npm.cmd run build` — PASS（3680 modules，只有既有大 chunk warning）；`git diff --check` — PASS。

## 关键输出

| 规模 | FTS P50/P95/P99 ms | Trigram P50/P95/P99 ms | Vector P50/P95/P99 ms | Top-K | 租户泄漏 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10k | 0.213 / 0.226 / 0.226 | 100.402 / 160.475 / 160.475 | 0.205 / 0.233 / 0.233 | 10 | 0 |
| 100k | 0.163 / 0.194 / 0.194 | 1017.611 / 1025.375 / 1025.375 | 0.167 / 0.179 / 0.179 | 10 | 0 |
| 1m | 0.166 / 0.181 / 0.181 | 10777.785 / 11313.107 / 11313.107 | 0.421 / 0.679 / 0.679 | 10 | 0 |

Vector 查询三档均使用 tenant partial HNSW 索引；没有跨租户结果。1m trigram P95=11,313.107ms，超过初始 3,000ms 目标，已明确记录为容量告警：发布前需提高相似度阈值或增加更窄的词法预过滤，并在隔离 staging 语料上复测。

## 数据库影响

- PostgreSQL 只读生产检查 PASS；性能样本只存在于临时会话。
- 没有永久表、索引、行或 schema 变更；事务 rollback + connection close 后 `public` 目录不存在 EVAL-018 对象。
- SQLite 禁止，未作为证据。

## 安全影响

- 报告只记录规模、分位延迟、索引名、Top-K 和租户泄漏计数。
- 未输出 DSN、密码、API Key、文档正文或设备凭据。
- 不访问外部 Provider，不执行网络设备写命令。

## 回滚方式

- 无生产 schema/data 回滚动作；临时事务 rollback，连接关闭即清理临时表和索引。
- 代码回滚：回滚 EVAL-018 合同、脚本、测试、报告和证据提交。

## 已知限制

- 五次重复下的 P99 是最大观测值，只用于容量诊断；正式容量规划仍需经批准的 staging 语料和并发模型。
- 当前本地 PostgreSQL 的 1m trigram 路径超过 3 秒初始目标，不能被解释为发布通过；该结果是明确的后续性能/索引优化告警。

## 最终结论

**PASS_WITH_CAPACITY_WARNING** — 10k/100k/1m PostgreSQL 样本、P50/P95/P99、Top-K、租户隔离、V1 基线、lint/build 和清理证据均完成；1m trigram 超目标容量风险已保留，发布硬门槛继续保持关闭。
