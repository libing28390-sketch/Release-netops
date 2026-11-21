# ING-004 walkthrough

```text
multipart file + reviewed official URL/metadata
                 |
                 v
bounded read -> filename/type/magic/UTF-8 checks
                 |
                 v
CAT-001/CAT-003 official URL preflight (no network)
                 |
                 v
ING-001 tenant idempotency job -> Source Registry row
                 |
                 v
server SHA-256 + immutable source-version provenance proof
                 |
                 v
fetched + continuation_required=true (parser tasks follow)
```

The proof is a hash-and-facts record, not an uploaded path or raw body. Replay
of the same tenant/source/content returns the existing version. The focused
tests use in-memory bytes and do not write a user-selected file path.

See [ING-004 Evidence](../knowledge-engine-v2/evidence/ING-004.md) and the
[ING-004 contract](../knowledge-engine-v2/architecture/ING-004-LOCAL-OFFICIAL-FILE-CONTRACT.yaml).
