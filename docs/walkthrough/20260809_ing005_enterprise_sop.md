# ING-005 walkthrough

```text
tenant SOP file
      |
      v
ING-004 filename/type/magic/size boundary
      |
      v
server builds internal.nexora.local tenant/content URI
      |
      v
enterprise + enterprise_sop + internal + INTERNAL metadata
      |
      v
immutable hash-only Source Version -> fetched continuation
```

There is no external URL and no network collection path. An uploader cannot
label a tenant SOP as PUBLIC or OFFICIAL. Later parsing and publication tasks
must retain the same domain and provenance facts.

See [ING-005 Evidence](../knowledge-engine-v2/evidence/ING-005.md) and the
[ING-005 contract](../knowledge-engine-v2/architecture/ING-005-ENTERPRISE-SOP-CONTRACT.yaml).
