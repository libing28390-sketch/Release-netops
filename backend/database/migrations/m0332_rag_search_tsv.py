"""Stored full-text vector for knowledge chunks (RAG refactor, V2 FTS leg).

The m0138 GIN index is an *expression* index on
``to_tsvector('simple', COALESCE(search_text, ''))``.  It finds matching rows,
but ``ts_rank_cd`` then has to re-parse every matching chunk, and with an
OR-query of common terms (``ospf``, ``vlan``) that is thousands of rows per
search: the 2026-11-22 benchmark measured ~220 ms for the FTS leg alone on a
10k-chunk corpus.  A stored ``tsvector`` column is parsed once at write time.

Follows DB-017 (expand -> backfill -> validate -> index), like m0331:

* this migration only adds a nullable column plus a trigger, which is a
  catalog change and does not rewrite ``ai_document_chunk``.  A ``GENERATED
  ... STORED`` column was not used because adding one rewrites the whole
  table under an ACCESS EXCLUSIVE lock;
* the trigger keeps ``search_tsv`` current for every new or changed chunk;
* existing rows are filled by ``scripts/rag_index_maintenance.py fts-index``
  in small batches, which then builds ``ix_ai_chunk_search_tsv`` with CREATE
  INDEX CONCURRENTLY (a migration runs inside a transaction, so it cannot);
* the retriever only uses the column once that index exists and is valid,
  so a half-filled column is never queried.

The expression must stay identical to the m0138 index so both paths match
exactly the same chunks.
"""

from __future__ import annotations

VERSION = 332
NAME = "rag_search_tsv"

FUNCTION_NAME = "nexora_rag_chunk_search_tsv"
TRIGGER_NAME = "trg_ai_document_chunk_search_tsv"
INDEX_NAME = "ix_ai_chunk_search_tsv"
TSV_EXPRESSION = "to_tsvector('simple', COALESCE({column}, ''))"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS search_tsv tsvector")
    cursor.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search_tsv := {TSV_EXPRESSION.format(column="NEW.search_text")};
            RETURN NEW;
        END;
        $$
        """
    )
    cursor.execute(f"DROP TRIGGER IF EXISTS {TRIGGER_NAME} ON ai_document_chunk")
    cursor.execute(
        f"CREATE TRIGGER {TRIGGER_NAME} BEFORE INSERT OR UPDATE OF search_text "
        f"ON ai_document_chunk FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}()"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Additive.  Dropping the index (DROP INDEX CONCURRENTLY
    # ix_ai_chunk_search_tsv) is enough to send the retriever back to the
    # m0138 expression index; the column and trigger are harmless.
    return None
