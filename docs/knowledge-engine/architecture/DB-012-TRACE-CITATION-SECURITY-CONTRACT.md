# DB-012 Trace, Citation, and Security Contract

## Contract summary

Retrieval evidence is separated into Retrieval Log, RAG Trace, Citation
Validation, and Security Audit. The logical records are
`ai_request_trace`, `kb_retrieval_log`, `kb_rag_trace`,
`kb_citation_validation`, and `audit_ai_security_event`. A trace stores
bounded identifiers, hashes, candidate counts, and fallback status; it does
not store a raw prompt, answer span, credential, or unrestricted document
body.

## Authorization and rollback

ACL and RBAC are enforced before a citation is verified or an answer is
completed. Tenant IDs, content hashes, and source freshness are checked in
order. A rollback disables the additive trace projection without removing V1
audit evidence; DB-013 remains the collection boundary.

## Final conclusion

The DB-012 Retrieval Log, RAG Trace, Citation Validation, Security Audit, ACL,
RBAC, hash, tenant, DB-013, V1, and 回滚 markers are documented.

Final Conclusion: PASS
