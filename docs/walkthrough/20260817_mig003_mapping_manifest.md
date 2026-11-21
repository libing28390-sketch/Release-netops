# MIG-003 Mapping and Manifest walkthrough

## Gate result

MIG-003 生成的是可重跑的迁移计划 artifact，不是数据库迁移。PostgreSQL `READ ONLY` 审计 PASS，SQLite 禁止，生产写入为 false。

## Mapping rule

```text
legacy key = (ai_document.tenant_id, ai_document.id)
v2 document id = UUID5(fixed_namespace, tenant_id + NUL + legacy_id)
v2 version id = UUID5(fixed_namespace, tenant_id + NUL + legacy_id + NUL + declared_hash_or_pending)
```

相同 tenant 和旧 ID 的重跑结果相同；不同 tenant 即使旧 ID 相同也不会碰撞。重复旧键或 UUID5 冲突会 fail-closed。

## Current snapshot

| 项目 | 结果 |
|---|---:|
| legacy documents | 156 |
| mapping entries | 156 |
| trusted | 0 |
| conditional reconciliation | 156 |
| source registry resolved | 0 |
| source registry unresolved | 156 |
| V2 ID collisions | 0 |
| production DB writes | false |

`source=upload` 不能被猜测成 Source Registry ID；所有条目先进入 reconciliation。Manifest 只保存必要的旧 ID、新 ID、hash、分类和动作，不保存原文或 metadata。

## Next dependency

MIG-004 将消费此 manifest 做 dry-run、断点、幂等和批次回滚设计；在 manifest/source/hash 审核前不得创建 V2 生产行。
