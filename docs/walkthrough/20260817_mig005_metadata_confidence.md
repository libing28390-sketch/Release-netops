# MIG-005 Metadata confidence walkthrough

## Classification flow

```text
metadata_json parse/object check
  -> server-owned/secret/instruction/size scan
  -> required keys + type/enum + UNKNOWN check
  -> parse status + lifecycle + exclusion + source trust check
  -> trusted | needs_validation | unusable
```

## Current PostgreSQL snapshot

| 等级 | 数量 | 行为 |
|---|---:|---|
| trusted | 0 | 可进入后续 reconciliation wave |
| needs_validation | 156 | review/reconcile 后才允许迁移 |
| unusable | 0 | quarantine/exclude |

154 行的主要差距是 legacy `rag_priority=P0` 与 V2 integer 0–100 契约不一致；另外 2 行缺少 parse status/required metadata。系统没有把这些差距隐藏成“可信”。

Manifest digest：`58bde50cb5712fef259ec56f2873c8379f04fc6ecca5a27b3bd23a35703cfb8c`；重跑保持一致。
