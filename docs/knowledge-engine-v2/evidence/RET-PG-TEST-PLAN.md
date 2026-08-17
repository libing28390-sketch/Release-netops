# RET PostgreSQL 测试方案修订证据

## 目标

把 RET-008 至 RET-022 的数据库与检索验收基准明确为真实 PostgreSQL。SQLite
不再作为 pg_trgm、PostgreSQL FTS、pgvector、JSONB、租户 SQL 或索引计划的
替代证据。

## 已落地

- 新增 `architecture/RET-008-022-POSTGRES-TEST-PLAN.yaml`，定义权威数据库、
  扩展、事务回滚、任务门禁和证据字段。
- 主任务清单的 RET 退出标准下新增强制环境规则。
- 新增 `scripts/knowledge_engine_v2_ret_pg_probe.py`，使用应用真实
  `DATABASE_URL` 连接 PostgreSQL，验证 m0138、`vector`、`pg_trgm`、FTS、
  trigram 阈值、向量余弦、租户/状态边界和 EXPLAIN，并在同一事务回滚。
- m0138 在 PostgreSQL 上缺少扩展时 fail-closed，不静默降级为文本列。

## 执行约束

默认 pytest 根 fixture 为历史兼容测试而强制 SQLite，因此不能把该 fixture
下的通过结果写成 RET 数据库门禁。RET 数据库证据必须单独执行：

```powershell
$env:PYTHONPATH = "backend"
.venv\\Scripts\\python.exe scripts/knowledge_engine_v2_ret_pg_probe.py
```

若 `DATABASE_URL`、扩展、权限或连接不可用，RET 任务标记为 `BLOCKED`，不得
用 SQLite 结果冒充 `PASS`。

## 当前状态

本文件只记录测试方案修订；RET-008 及后续任务仍需逐项完成实现、真实 PG
验证、Evidence、lint/build 和回归门禁后，才能更新任务清单复选框。
