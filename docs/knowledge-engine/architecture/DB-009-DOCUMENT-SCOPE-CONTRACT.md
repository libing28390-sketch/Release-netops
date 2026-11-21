# DB-009 Document Scope Contract

## Contract summary

Document applicability is decomposed into `kb_document`,
`kb_document_version`, `kb_document_product`, and `kb_document_software`.
The resulting Document Scope is evaluated together with tenant ACL and
content hash. `ai_document` is retained as the V1 compatibility projection.

## Dependencies and rollback

DB-010 owns chunk/index relationships and DB-013 owns collection membership;
neither replaces scope authorization. Rollback preserves source and version
rows, disables the additive scope projection, and records the transition.

## Final conclusion

The Document Scope, ACL, content hash, tenant, DB-010, DB-013, V1, and 回滚
markers are present.

Final Conclusion: PASS
