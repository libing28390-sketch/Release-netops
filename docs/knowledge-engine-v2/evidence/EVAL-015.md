# EVAL-015 Evidence

## Task ID

EVAL-015 — 覆盖成功、非法输入、权限拒绝、空数据和依赖失败。

## 目标

在 PostgreSQL-only 规则下验证五类边界：成功路径、非法输入、权限拒绝、空数据和依赖失败；持久化探针必须回滚，V1 不回归，不能使用 SQLite。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-015-INPUT-FAILURE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval015_input_failure_check.py`
- `tests/knowledge_engine_v2/test_eval015_input_failure.py`
- `docs/knowledge-engine-v2/eval/eval-input-failure-v1.manifest.json`
- `docs/walkthrough/20260817_eval015_input_failure.md`

## 实现内容

- 固化成功、非法输入、权限、空数据、依赖失败五类验收 contract。
- PostgreSQL 探针：Provider/ACL/Fallback、Reindex 成功/embedding 失败原子性、重复内容约束、V1 空结果基线。
- 纯合约测试使用 `-p no:conftest`，不加载历史 SQLite fixture。
- 明确排除 `backend/tests/ai/test_kui_012_document_actions.py`：该历史文件硬编码 `sqlite3`，不符合当前 PG-only 验收政策，因此不运行、不计数、不宣称通过。

## 执行命令与结果

环境：`DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/netops`，`PYTHONPATH=backend`。

1. `.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval015_input_failure_check.py tests\knowledge_engine_v2\test_eval015_input_failure.py` — PASS。
2. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval015_input_failure_check.py` — **PASS**；`database=postgresql`、`sqlite=not_used`；五类场景全部 PASS；`pure_tests=69`；所有 PG 探针 rollback/cleanup PASS；`production_database_write=false`。
3. `.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval015_input_failure.py -q -p no:cacheprovider` — **2 passed**。
4. 纯合约测试：`.venv\Scripts\pytest.exe -p no:conftest backend/tests/ai/test_api_v2_contracts.py backend/tests/ai/test_sec_001_020_security_gateway.py backend/tests/ai/test_security_gateway.py backend/tests/ai/test_ingestion_pipeline_state_machine.py backend/tests/ai/test_ingestion_idempotency.py backend/tests/ai/test_ing006_document_parser_adapters.py backend/tests/ai/test_ing008_document_security_scan.py -q -p no:cacheprovider` — **69 passed**；无 SQLite 连接。
5. V1 baseline（PostgreSQL）— **10/10**；retrieval_accuracy=1.0、citation_accuracy=1.0、wrong_vendor_rate=0.0、version_conflict_rate=0.0、rollback=transaction_rollback。
6. `git diff --check` — PASS。

## 关键输出

- Success：Reindex changed projection、original content preservation PASS。
- Invalid input：同租户同 source/content hash 重复被拒绝，跨租户相同 hash 允许，探针 rollback=true。
- Permission：Provider ACL tenant-scoped、route fallback、duplicate model boundary PASS。
- Empty：V1 Q07 `CloudEngine 6800 OSPF config` 返回 `[]`，整体 retrieval/citation accuracy 保持 1.0。
- Dependency failure：embedding provider failure 不产生部分 chunk，concurrent edit 被 CAS 拒绝。
- PostgreSQL 探针均未导入 `sqlite3`；排除文件是唯一硬编码 SQLite 的旧兼容测试。

## 数据库影响

所有持久化场景通过 PostgreSQL 18.4，Provider/Reindex/duplicate/V1 fixtures 均在事务内回滚；未写入生产数据，SQLite 未作为证据。

## 安全影响

验证 tenant-scoped ACL、未知/不安全输入 fail-closed、重复内容边界、embedding 依赖失败原子性和并发 CAS；不访问外部网络，不输出密钥。

## 回滚方式

每个 PostgreSQL probe 在 finally/事务边界 rollback；代码变更可按提交回滚，不需要恢复生产数据。

## 已知限制

KUI-012 历史动作测试因硬编码 `sqlite3` 被明确排除，后续如需验收必须先改成 PostgreSQL 临时事务测试；本任务不将其列为阻断，因为其余独立矩阵已完整通过。

## 最终结论

**PASS** — EVAL-015 五类输入/失败边界、PostgreSQL-only、回滚和 V1 不回归要求满足；SQLite 测试未作为验收依据。
