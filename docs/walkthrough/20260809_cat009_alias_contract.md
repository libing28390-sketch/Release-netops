# CAT-009 Alias Contract Walkthrough

## Resolution flow

```text
query
  ↓ NFKC/casefold/whitespace/dash normalization
exact → canonical → prefix candidates → trigram candidates → UNKNOWN
```

同一租户同一规范化 Alias 跨型号时返回 `ambiguous_pending_review`，不会选择第一条；跨租户记录不可见。Prefix/trigram 只作候选排序，Alias 不提供网络设备或 driver 权限。

## Verification

- CAT-009 focused: 9 passed。
- CAT-001..009 + DB-006/007 + RAG regression: 74 passed。
- compileall、YAML/secret/diff gates PASS；无生产 DDL。
