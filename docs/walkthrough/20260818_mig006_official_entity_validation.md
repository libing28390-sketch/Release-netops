# MIG-006 Official entity validation walkthrough

```text
legacy ai_document
  -> tenant-scoped source registry/version lookup
  -> CAT-001 official host/path scope (no network fetch)
  -> reviewed catalog snapshot check
  -> exact/canonical unique match only
  -> verified | needs_validation | unusable
```

本次运行的 PostgreSQL 现场没有 DB-006/DB-007 reviewed catalog 表，且 156 行 legacy 文档的来源仍为未绑定的上传来源。因此所有文档都进入 `needs_validation`，没有从正文、型号字符串或软件 train 反推官方实体。`verified` 只有在来源、目录、OS、版本和平台全部有明确证据时才会出现。

| 结果 | 数量 | 后续动作 |
|---|---:|---|
| verified | 0 | 可进入 MIG-007 |
| needs_validation | 156 | 重新取官方来源/人工复核 |
| unusable | 0 | quarantine/exclude |

Manifest digest：`38ec2aab6c727fa426f0273111b0ae3965b5ddb5dbed65859041735b3a9cb227`。
