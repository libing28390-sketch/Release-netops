# ING-014 Source Merge Contract

ING-014 keeps the URL-level source registry and immutable source-version facts
separate while allowing equal server-owned bytes from compatible URLs to reuse
one tenant-scoped `kb_document_version`.

The merge decision is fail-closed. Trust level, parser name/version and
document kind must match, and the candidate cannot be disabled, deleted,
quarantined or purged. A different hash creates a new document/version path;
an incompatible same hash also remains separate. A source from another tenant
is never a candidate.

`kb_document_source` stores the source observation and its bounded counter. It
does not copy raw content. The source registry and source version tables are the
authority for URL, hash, byte size, parser and trust facts; mutable caller
dictionaries cannot forge a merge. The migration is additive and release-gated,
and V1 `ai_document`/`ai_document_chunk` rows are untouched.
