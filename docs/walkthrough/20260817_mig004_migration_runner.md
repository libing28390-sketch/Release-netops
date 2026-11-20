# MIG-004 Migration runner walkthrough

## Safe execution flow

```text
load MIG-003 manifest
  -> verify manifest SHA-256 and redacted fields
  -> load matching checkpoint (or start at offset 0)
  -> process bounded batch
       dry-run: count only
       apply: begin -> idempotent upsert/skip -> commit
       failure: rollback current batch -> retry_wait at previous cursor
  -> atomically persist redacted checkpoint
```

## Current gate

| 指标 | 结果 |
|---|---:|
| manifest entries | 156 |
| batch size | 25 |
| dry-run processed | 156 |
| committed batches | 7 |
| target inserts | 0 |
| production DB writes | false |
| SQLite | forbidden |
| PostgreSQL temp rollback | before 1 → after 0 |

已完成 checkpoint 再次 apply 时会核验目标是否仍存在；全部存在返回 idempotent noop，任何缺失都会阻断而不会静默补写。当前 source/hash reconciliation 未完成，生产 apply guard 保持关闭。
