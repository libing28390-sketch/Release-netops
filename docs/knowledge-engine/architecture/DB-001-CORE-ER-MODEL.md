# DB-001 Core ER Model

## Contract summary

The V1 PostgreSQL model separates tenant-owned knowledge documents from
`kb_document_version`, `kb_chunk_embedding`, and the `ai_model_route`
projection. Document identity, version identity, chunk identity, embedding
identity, and retrieval routing remain independently auditable.

## Migration and rollback

PostgreSQL is the production persistence target. Foreign keys and tenant
predicates are part of the model boundary. A 回滚 preserves V1 rows and
removes only an explicitly additive projection after dependent reads have
been disabled; no source document or embedding is silently rewritten.

## Final conclusion

The core entity relationships and PostgreSQL/V1 rollback evidence are
available for review.

Final Conclusion: PASS
