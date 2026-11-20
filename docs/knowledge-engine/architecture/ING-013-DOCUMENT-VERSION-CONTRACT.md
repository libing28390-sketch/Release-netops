# ING-013 Document Version Contract

ING-013 establishes the first durable V2 document lineage boundary. Within a tenant, a normalized official URL identifies one stable document. A source version with a new server-owned SHA-256 appends an immutable `kb_document_version`; the previous version is retained through `supersedes_version_id`. A repeated hash returns the existing version and does not rewrite facts.

The implementation is additive and shadow-only. `m0117_knowledge_v2_document_versions` creates `kb_document` and `kb_document_version` with tenant-scoped unique constraints, source/document composite references, and an immutable fact trigger. Collection membership and explicit Product/OS applicability remain governed by DB-013/DB-009 follow-up work. V1 `ai_document` and `ai_document_chunk` are not modified or deleted.

The outbound boundary intentionally keeps only a verified source reference when raw bytes are not retained in memory. Lifecycle activation, parsing, chunk generation and publication remain later gates.

