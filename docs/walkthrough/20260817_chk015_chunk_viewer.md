# CHK-015 Chunk viewer walkthrough

The existing document detail route now returns a bounded, ordered chunk
projection.  Each chunk keeps its stable id, section, ordinal, role/type,
token/hash facts, candidate flag and chunk/parser/document/index versions.
When available, the response includes the same-document `parent_chunk` and
explicit or immediate `neighbors`, plus redacted `metadata`, heading path and
`source_locator` objects.

The Knowledge Management drawer renders those fields as on-demand sections:
content remains readable in order, Parent and Neighbor context can be expanded,
and Metadata / source locator / version facts are visible without exposing
embedding vectors or secret/identity metadata.  The document list remains a
summary-only response.

The PostgreSQL-only probe inserts three temporary V1-compatible chunks, checks
all relations and redaction, rejects a cross-tenant lookup, and rolls back the
transaction.  SQLite is not used as an acceptance backend.

