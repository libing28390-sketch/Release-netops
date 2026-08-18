# MIG-008 Consistency audit walkthrough

~~~text
document inventory + MIG-006 expected count
  -> content hash (normalized body)
  -> parent/child version + embedding contract
  -> chunk orphan/ordinal/hash checks
  -> tenant/ACL inheritance and metadata identity scan
  -> PASS or BLOCKED with stable reason codes
~~~

| 项目 | 结果 |
|---|---:|
| legacy documents / expected | 156 / 156 |
| legacy chunks | 474 |
| orphan chunks | 0 |
| version/index mismatch | 0 |
| unverifiable document hashes | 2 |
| unverifiable chunk hashes/embeddings | 2 / 2 |
| chunk metadata identity leaks | 472 |
| audit outcome | BLOCKED |

CHUNK_METADATA_IDENTITY_LEAK 是真实权限边界问题：Chunk 只能继承父文档 tenant/ACL，不能把身份、ACL 或角色键作为可检索 metadata。修复后必须在 PostgreSQL 上重新运行同一审计。
