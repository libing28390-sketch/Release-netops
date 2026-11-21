# MIG-002 Source-first walkthrough

## Gate result

MIG-002 完成的是迁移准入门禁，不是生产数据迁移。PostgreSQL 只读审计 PASS；SQLite 不参与验收；没有 DDL、INSERT、UPDATE 或 DELETE。

## 当前快照分类

| 对象 | 数量/结果 |
|---|---:|
| legacy documents | 156 |
| original content present | 156 |
| source provenance present | 156 |
| declared hash present | 154 |
| original hash match | 0 |
| normalized hash match | 154 |
| trusted source candidates | 0 |
| reconciliation required | 156 |
| legacy chunks | 474 |
| direct chunk copy | forbidden |
| direct embedding copy | forbidden |

## 迁移顺序

```text
PostgreSQL read-only inventory
  -> source bytes + SHA-256 manifest
  -> immutable document version/provenance
  -> quarantine/manual reconciliation for conditional rows
  -> rebuild append-only chunk generation
  -> gateway-pinned embedding recomputation
  -> shadow recall/latency gate
  -> publish only the ready generation
```

当前 156 行均需先 reconciliation；MIG-003 负责建立 manifest 和 ID 映射。任何未证明的 Chunk/Embedding 都只能作为非权威旧证据保留，不能直接迁移或发布。

## V1 non-regression

V1 PostgreSQL baseline 10/10：retrieval accuracy 1.0、citation accuracy 1.0、wrong vendor rate 0、version conflict rate 0；审计过程无生产数据库写入。
