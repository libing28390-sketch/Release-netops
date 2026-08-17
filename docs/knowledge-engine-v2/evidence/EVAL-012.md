# EVAL-012 Evidence

## Task ID

EVAL-012

## 目标

覆盖 Source、Document、Version、Chunk、Reindex 生命周期测试；所有持久化验收必须使用 PostgreSQL，SQLite 不得替代。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-012-LIFECYCLE-TEST-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval012_lifecycle_check.py`
- `scripts/knowledge_engine_v2_kui015_pg_probe.py`（修复固定探针 ID/commit 导致重复执行失败；改为唯一 ID + 事务回滚）
- `tests/knowledge_engine_v2/test_eval012_lifecycle.py`
- `docs/knowledge-engine-v2/eval/eval-lifecycle-v1.manifest.json`
- `docs/walkthrough/20260817_eval012_lifecycle.md`

## 实现内容

- 新增生命周期 coverage validator 和 PG probe runner，强制检查 `DATABASE_URL` 为 PostgreSQL，并以子进程逐个运行五个权威探针。
- Source、Document、Version、Chunk、Reindex 五个边界均覆盖租户、原子性、脱敏、V1 preservation 和 rollback/cleanup。
- KUI-015 原探针曾因固定 ID 和提前 `commit` 导致第二次运行 `UniqueViolation`；已改为唯一后缀并移除 commit，使 append-only observation 可安全 rollback、可重复执行。

## 执行命令

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval012_lifecycle_check.py
.venv\Scripts\python.exe -m pytest tests\knowledge_engine_v2\test_eval012_lifecycle.py -q -p no:cacheprovider
.venv\Scripts\python.exe scripts\knowledge_engine_v2_v1_baseline_pg.py
.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval012_lifecycle_check.py tests\knowledge_engine_v2\test_eval012_lifecycle.py scripts\knowledge_engine_v2_kui015_pg_probe.py
git diff --check
```

## 测试结果

PASS。

- 生命周期 runner：`status=PASS`，5 probes 全部报告 PostgreSQL，`sqlite=not_used`，`production_write=false`，`rollback_or_cleanup=true`。
- Source：status projection、bounded observation、tenant isolation、no raw body/metadata leak、重复运行 PASS。
- Document：confirmation gate、impact preview、disable/enable recovery、delete atomicity、metadata-only ledger、tenant isolation PASS。
- Version：metadata-only compare、publish pointer、supersede、rollback/idempotency、immutable source facts、tenant scope PASS。
- Chunk：parent/neighbor、source locator、version lineage、metadata redaction、tenant isolation、V1 preservation、rollback PASS。
- Reindex：changed projection、original content preservation、dry-run、provider failure atomicity、concurrent CAS rejection、rollback PASS。
- EVAL-012 wrapper：`2 passed`；PG runner 重复执行也 PASS。
- V1 PostgreSQL baseline：`10/10`，retrieval_accuracy `1.0`，wrong_vendor_rate `0.0`，version_conflict_rate `0.0`，citation_accuracy `1.0`，transaction rollback。
- YAML / py_compile / `git diff --check`：PASS。

## 数据库影响

- 使用本机 PostgreSQL `netops` 开发库；无新增 migration，无生产写入。
- Source/Version/Document/Chunk/Index/Reindex fixture 均在事务 rollback 或唯一命名 cleanup 下完成。
- SQLite 未作为任何 EVAL-012 验收证据。

## 安全影响

- 严格 tenant boundary；跨租户读取/动作拒绝。
- Chunk metadata、action ledger、refresh status 不返回正文、secret、raw metadata 或 SQL。
- 删除动作要求明确确认，重建失败保持原始内容和旧 projection。

## 回滚方式

- 应用回滚：关闭 V2 lifecycle action/reindex 路径，保留 V1 projection。
- 数据回滚：所有 PG 探针 transaction rollback；KUI-015 使用唯一 ID，不执行 append-only DELETE。

## 已知限制

- 外部官方网络采集未在本任务中执行，使用已审核的 Mock/fixture 与本地 PG probes。
- 浏览器可见生命周期操作属于 EVAL-017；本任务验证服务/数据库合同。

## 最终结论

PASS
