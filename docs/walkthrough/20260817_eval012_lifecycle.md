# EVAL-012 生命周期验证

## 验证目标

验证 Source → Document → Version → Chunk → Reindex 的完整生命周期和失败回滚路径。

## 操作路径

1. 设置 `DATABASE_URL` 到本机 PostgreSQL `netops`，不使用 SQLite。
2. 执行 EVAL-012 runner；它按 Source、Document、Version、Chunk、Reindex 顺序启动五个现有 PG 探针。
3. 检查每个探针的租户隔离、原子性、脱敏、V1 preservation 和 rollback/cleanup 结果。
4. 运行 EVAL-012 wrapper 和 V1 PostgreSQL baseline。

## 预期结果

- 五个 probe 全部 PASS，数据库字段为 PostgreSQL，SQLite 状态为 `not_used`。
- Source observation 可重复；Document action 需确认；Version supersede/rollback 幂等；Chunk lineage/metadata 脱敏；Reindex dry-run/provider failure/CAS 不破坏旧数据。

## 实际结果

PASS：5/5 PostgreSQL probes、EVAL-012 wrapper 2 passed、V1 baseline 10/10；YAML、py_compile、diff check 通过。
