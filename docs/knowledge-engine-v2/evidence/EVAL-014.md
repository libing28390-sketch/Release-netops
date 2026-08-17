# EVAL-014 Evidence

## Task ID

EVAL-014 — 覆盖迁移、新装、重复迁移、回填、约束、回滚和恢复。

## 目标

使用 PostgreSQL 临时数据库验证 V1 基线引导、全部版本化迁移、重复执行、数据回填幂等、约束/事实保护、失败事务回滚、修复重试和历史漂移 fail-closed；不得写入当前应用生产数据库，不得使用 SQLite。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-014-MIGRATION-RECOVERY-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval014_migration_check.py`
- `tests/knowledge_engine_v2/test_eval014_migration.py`
- `docs/knowledge-engine-v2/eval/eval-migration-recovery-v1.manifest.json`
- `docs/walkthrough/20260817_eval014_migration.md`

## 实现内容

- 创建唯一命名的临时 PostgreSQL database，调用真实 `schema._init_db_logic` 与 `run_migrations(..., strict_history=True)`。
- 验证 fresh bootstrap、全部 150 个迁移、重复执行 0 pending、V1 表计数保持不变。
- 对 m0148 `tags_json` 执行对象/null/空值到数组的回填，重复升级保持幂等，事务回滚后临时表消失。
- 对 source registry/version 执行 PostgreSQL CHECK、tenant canonical UNIQUE、tenant/source FK 和 immutable fact trigger 负向验证。
- 注入一次会创建表和行后失败的迁移，验证 DDL/数据回滚、高版本不执行；修复后重试成功；未知 history 以 strict 模式拒绝继续。

## 执行命令与结果

环境：`DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/netops`，`PYTHONPATH=backend`。

1. `.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval014_migration_check.py tests\knowledge_engine_v2\test_eval014_migration.py` — PASS。
2. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval014_migration_check.py` — **PASS**；临时 PG 库新装 150/150、重复 0、回填幂等、约束 5/5 拒绝、失败回滚/修复重试/漂移阻断全部 PASS；`database=postgresql`、`sqlite=not_used`；临时库已删除。
3. `.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval014_migration.py -q -p no:cacheprovider` — **2 passed**。
4. `.venv\Scripts\python.exe scripts\knowledge_engine_v2_v1_baseline_pg.py` — PostgreSQL **10/10**；retrieval_accuracy=1.0、citation_accuracy=1.0、wrong_vendor_rate=0.0、version_conflict_rate=0.0、production_database_write=false、rollback=transaction_rollback。
5. PostgreSQL 查询 `pg_database WHERE datname LIKE 'nexora_eval014_%'` — 返回空集，确认无临时库残留。
6. `git diff --check` — PASS。

## 关键输出

- PostgreSQL authority：18.4；vector/pg_trgm 扩展可用。
- Fresh：`first_applied=150`、`history_versions=150`、`pending_after_first=[]`。
- Repeat：`second_applied=0`、`pending_after_second=[]`、V1 表计数未变。
- Backfill：`empty/null/blank -> []`，`valid ["network"]` 保持不变；重复升级结果一致；rollback=true。
- Constraints：source_type `23514`、byte_size `23514`、canonical unique `23505`、tenant FK `23503`、immutable trigger `P0001` 均按预期拒绝。
- Recovery：首次失败应用 0、部分 DDL 回滚、高版本未调用；修复重试应用 2；未知 999 history strict 阻断。

## 数据库影响

只创建并删除唯一命名的临时 PostgreSQL database；当前 `netops` 仅作为服务器 authority，未执行生产写入。无 SQLite 连接、fixture 或验收结果。

## 安全影响

验证租户复合 FK、canonical 唯一边界、不可变来源事实和严格历史漂移保护；不访问外部网络，不输出凭据。

## 回滚方式

探针 finally 中关闭连接并 `DROP DATABASE` 临时库；探针失败时仍执行清理。生产数据库不执行 DDL/DML，因此无需生产数据恢复。

## 已知限制

本门禁不执行真实生产迁移，也不覆盖需要人工批准的发布窗口；它验证真实迁移代码在隔离 PostgreSQL 数据库中的行为。历史 `backend/tests/database` 中的 SQLite fixture 不属于 EVAL-014 验收。

## 最终结论

**PASS** — EVAL-014 的 PostgreSQL 新装、重复、回填、约束、回滚、恢复和 V1 保持要求均满足。
