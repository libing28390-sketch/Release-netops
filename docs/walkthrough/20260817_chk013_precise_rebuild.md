# CHK-013 precise rebuild verification

CHK-013 closes the derived-data gap after a document body changes.  The
reindex service now keeps the immutable source fact separate from the latest
normalized body: Front Matter is read from `original_content`, while
Rechunk/Reembed/Reindex consume `normalized_content` when present.  It updates
the document and replaces its old chunks in one transaction only after all
new embeddings pass validation.

A tenant and `updated_at` compare-and-set fences a worker that started from a
stale document snapshot.  Dry-run, provider failure, and a concurrent edit
leave the previous chunk projection untouched.  Retrieval-cache invalidation
still happens only after a successful commit.

The PostgreSQL-only probe uses the real V1-compatible tables, verifies a
changed body gets a different chunk/embedding projection, preserves
`original_content`, exercises dry-run and provider failure atomicity, forces a
concurrent edit, and rolls back every probe write.  SQLite is not used as an
acceptance backend.
