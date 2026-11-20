# DB-013 Collection Document Reference

## Contract summary

Collection membership is represented by `kb_collection` and
`kb_collection_document`; the `Collection Document` relation and its `kb_document`
parent are not inferred
from a UI directory. The service boundary retains `create_knowledge_base`,
`list_knowledge_bases`, `list_documents`, `get_document_detail`,
`delete_document`, and `batch_delete_documents` as explicit operations.

## Security and rollback

Membership, Metadata, tenant, RBAC, and ACL checks are independent. DB-009
owns document scope and DB-014 owns the relational/JSONB boundary. Rollback
retains source documents and restores the previous collection projection;
destructive deletion requires an explicit lifecycle policy.

## Final conclusion

The DB-013 Collection, tenant, RBAC, ACL, DB-009, DB-014, V1, and 回滚
markers are present.

Final Conclusion: PASS
