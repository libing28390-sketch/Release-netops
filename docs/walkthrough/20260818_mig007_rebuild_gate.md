# MIG-007 Rebuild gate walkthrough

```text
MIG-006 manifest
  -> verified-only eligibility
  -> Parse / Normalize / Classify
  -> Chunk
  -> Embed (pinned provider + dimension)
  -> Index
  -> Validate / Commit
```

现场 manifest 没有 `verified` 行，所以流程在 eligibility 处安全停止：156 行保留在 `needs_validation`，Provider 调用为 0，旧 474 个 Chunk 不动。该结果是阻断，不是成功重建；补齐官方来源证据后重新运行 gate 即可恢复。

| 检查项 | 结果 |
|---|---|
| PostgreSQL read-only | PASS |
| verified documents | 0 |
| skipped for review | 156 |
| provider calls | 0 |
| production writes | 0 |
| rollback path | V1 projection remains active |
