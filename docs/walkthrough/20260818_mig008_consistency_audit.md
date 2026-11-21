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
| excluded (quarantined) document hashes | 2 |
| excluded (quarantined) chunk hashes/embeddings | 2 / 2 |
| chunk metadata server-owned identity leaks | 0 |
| audit outcome | PASS |

两条缺失 hash/Embedding 的 API fixture 父文档均为 `quarantined`，因此只计入 `excluded_*`，不进入检索投影。Chunk 仍只能继承父文档 tenant/ACL，不能携带 server-owned tenant/ACL/credential/role 键；当前 PostgreSQL 复核为 0。MIG-009 仍受 MIG-007 verified source/entity 门禁约束。
