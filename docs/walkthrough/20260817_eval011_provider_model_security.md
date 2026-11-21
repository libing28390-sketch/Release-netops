# EVAL-011 Provider / Model / Fallback / Security 验证

## 验证目标

确认多 Provider、多 Model、模型切换、Fallback、ACL 与 API Key 安全合同均有测试，并且所有持久化证据来自 PostgreSQL。

## 操作路径

1. 运行 coverage validator，确认冻结的 LLM PostgreSQL 计划和测试矩阵完整。
2. 在 `DATABASE_URL=postgresql://.../netops` 下运行 LLM PG probe；探针启动显式事务，执行 m0139/m0140/m0141 幂等迁移和临时 rows，最后 rollback。
3. 运行 Provider/Model、Security Gateway、API contract 后端测试。
4. 运行 EVAL-011 wrapper，它会拒绝非 PostgreSQL URL，并再次执行 PG probe。
5. 运行 V1 PostgreSQL baseline、前端 lint 和 production build。

## 预期结果

- Provider CRUD、model switch、fallback、tenant/role/user ACL、key rotation/audit 和稳定错误码均有覆盖。
- PG probe 输出 `rollback=true`，不产生持久化测试数据。
- SQLite 不得出现在 EVAL-011 验收证据中。

## 实际结果

PASS：coverage validator PASS；PG probe PASS；后端 33 passed；EVAL-011 wrapper 2 passed；V1 baseline 10/10；lint/build/compile/diff PASS。
