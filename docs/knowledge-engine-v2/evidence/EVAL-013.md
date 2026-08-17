# EVAL-013 Evidence

## Task ID

EVAL-013 — 覆盖检索、引用、No Match、Ambiguous 和版本冲突测试。

## 目标

在不使用 SQLite 的前提下，验证 PostgreSQL 检索加速路径、租户与状态边界、引用安全、无匹配、歧义候选和版本冲突 fail-closed 行为，并确认 V1 基线不回归。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-013-RETRIEVAL-CITATION-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval013_retrieval_citation_check.py`
- `tests/knowledge_engine_v2/test_eval013_retrieval_citation.py`
- `docs/knowledge-engine-v2/eval/eval-retrieval-citation-v1.manifest.json`
- `docs/walkthrough/20260817_eval013_retrieval_citation.md`

## 实现内容

- 固化 EVAL-013 PostgreSQL-only contract，明确 SQLite forbidden、事务回滚、禁止生产写入。
- 调用真实 `ret_pg_probe` 验证 FTS、pg_trgm、pgvector、租户/状态过滤、EXPLAIN 和 m0138 幂等列/索引。
- 调用 PostgreSQL V1 baseline 验证 Q07 No Match、Q05 bounded Ambiguous、Q03/Q04 版本选择与冲突率。
- 静态锁定 RET normalizer/resolver/retrieval contract 与 CIT grounding/security 测试。

## 执行命令与结果

环境：`DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/netops`，`PYTHONPATH=backend`。

1. `.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval013_retrieval_citation_check.py tests\knowledge_engine_v2\test_eval013_retrieval_citation.py` — PASS。
2. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval013_retrieval_citation_check.py` — PASS；`database=postgresql`、`sqlite=not_used`；RET rollback PASS；V1 retrieval/citation 1.0；version conflict rate 0.0；Q07/Q05/Q03/Q04 全部 PASS。
3. `.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval013_retrieval_citation.py -q -p no:cacheprovider` — **2 passed**。
4. `.venv\Scripts\pytest.exe -p no:conftest backend/tests/ai/test_ret_001_003_query_normalizer.py backend/tests/ai/test_ret_004_007_product_resolution.py backend/tests/ai/test_ret_011_020_retrieval_contract.py backend/tests/ai/test_cit_001_010_grounding.py -q -p no:cacheprovider` — **19 passed**；这些是无持久化连接的纯合约测试，未加载历史 SQLite fixture。
5. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_v1_baseline_pg.py` — PostgreSQL **10/10**；retrieval_accuracy=1.0、citation_accuracy=1.0、wrong_vendor_rate=0.0、version_conflict_rate=0.0、production_database_write=false、rollback=transaction_rollback。
6. `git diff --check` — PASS。

## 关键输出

- PostgreSQL 18.4；`vector 0.8.6`；`pg_trgm 1.6`。
- RET FTS candidates=2、trigram candidates=2、vector candidates=2；tenant scoped ids 仅 `__ret_pg_probe_chunk_t1`；EXPLAIN 捕获 `Bitmap Heap Scan`/`Bitmap Index Scan`。
- No Match：Q07 返回空集。
- Ambiguous：Q05 返回两个受控候选 `ospf-v300`、`ospf-v600`。
- Version conflict：Q03/Q04 各自只返回对应版本，V1 conflict rate=0.0；CIT validator 对 vendor/version 冲突拒绝引用。

## 数据库影响

所有持久化验证使用 PostgreSQL。RET probe 与 V1 baseline 使用事务/临时表并回滚，无生产行、迁移历史或 schema 版本残留；SQLite 未作为验收证据。

## 安全影响

验证租户/状态过滤、引用 vendor/version allowlist、未发布文档拒绝、缺少证据拒答和 secret/URL 脱敏；未进行外部网络调用。

## 回滚方式

探针在单事务中执行，失败或成功均 rollback；无需数据恢复。代码变更可通过提交回滚，不涉及生产 DDL。

## 已知限制

本任务的 RET/CIT 纯函数合约测试不建立数据库连接；数据库相关验收只认 PostgreSQL 探针和 PostgreSQL V1 baseline。ING-020/ING-021 的浏览器认证阻断不属于 EVAL-013。

## 最终结论

**PASS** — EVAL-013 的检索、引用、No Match、Ambiguous、版本冲突、PostgreSQL-only、回滚和 V1 不回归要求均满足。
