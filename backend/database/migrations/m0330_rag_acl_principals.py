"""Project document ACLs into an indexed principal array for SQL retrieval.

The retriever used to load every metadata-eligible chunk into Python and run
``rag_policy.document_is_visible`` row by row.  The V2 retrieval engine pushes
the ACL check into PostgreSQL, so it needs the ACL in a form an index can use.

``ai_document.acl_principals`` holds the principals that may see a document:

* ``'*'``        -- visible to everyone (no ACL / empty ACL object)
* ``'u:<id>'``   -- a user listed in ``users`` / ``user_ids``
* ``'r:<role>'`` -- a role listed in ``roles``
* ``'s:<site>'`` -- a site listed in ``sites`` / ``site_ids``
* ``{}``         -- nobody (malformed ACL, non-object JSON, or an ACL with no
                    supported dimension); this mirrors the fail-closed Python
                    policy.

A trigger keeps the column in sync with ``acl_json`` for every writer, so no
service code has to remember it.  The SQL filter is an additional, earlier
gate: the retriever still re-checks every returned row with
``document_is_visible``, so any divergence can only lose recall, never expose
a document.
"""

from __future__ import annotations


VERSION = 330
NAME = "rag_acl_principals"


# NOTE: no '?' characters may appear in these statements -- the migration
# cursor rewrites '?' placeholders for psycopg2.
_PRINCIPALS_FUNCTION = """
CREATE OR REPLACE FUNCTION nexora_rag_acl_principals(raw TEXT)
RETURNS TEXT[]
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    parsed JSONB;
    result TEXT[] := ARRAY[]::TEXT[];
    entry RECORD;
    item JSONB;
    prefix TEXT;
    principal TEXT;
BEGIN
    IF raw IS NULL OR raw = '' THEN
        RETURN ARRAY['*'];
    END IF;
    BEGIN
        parsed := raw::jsonb;
    EXCEPTION WHEN others THEN
        RETURN ARRAY[]::TEXT[];
    END;
    IF jsonb_typeof(parsed) <> 'object' THEN
        RETURN ARRAY[]::TEXT[];
    END IF;
    IF parsed = '{}'::jsonb THEN
        RETURN ARRAY['*'];
    END IF;
    FOR entry IN SELECT e.key AS k, e.value AS v FROM jsonb_each(parsed) AS e LOOP
        prefix := CASE entry.k
            WHEN 'users' THEN 'u:'
            WHEN 'user_ids' THEN 'u:'
            WHEN 'roles' THEN 'r:'
            WHEN 'sites' THEN 's:'
            WHEN 'site_ids' THEN 's:'
            ELSE NULL
        END;
        CONTINUE WHEN prefix IS NULL;
        IF jsonb_typeof(entry.v) = 'array' THEN
            FOR item IN SELECT a.value FROM jsonb_array_elements(entry.v) AS a LOOP
                principal := btrim(item #>> '{}');
                IF principal IS NOT NULL AND principal <> '' THEN
                    result := array_append(result, prefix || principal);
                END IF;
            END LOOP;
        ELSIF jsonb_typeof(entry.v) <> 'null' THEN
            principal := btrim(entry.v #>> '{}');
            IF principal IS NOT NULL AND principal <> '' THEN
                result := array_append(result, prefix || principal);
            END IF;
        END IF;
    END LOOP;
    RETURN result;
END;
$$
"""

_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION nexora_rag_acl_principals_sync()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.acl_principals := nexora_rag_acl_principals(NEW.acl_json::text);
    RETURN NEW;
END;
$$
"""


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return

    cursor.execute("ALTER TABLE ai_document ADD COLUMN IF NOT EXISTS acl_principals TEXT[]")
    cursor.execute(_PRINCIPALS_FUNCTION)
    cursor.execute(_TRIGGER_FUNCTION)
    cursor.execute("DROP TRIGGER IF EXISTS trg_ai_document_acl_principals ON ai_document")
    cursor.execute(
        """
        CREATE TRIGGER trg_ai_document_acl_principals
        BEFORE INSERT OR UPDATE OF acl_json ON ai_document
        FOR EACH ROW EXECUTE FUNCTION nexora_rag_acl_principals_sync()
        """
    )
    # ai_document holds one row per document (not per chunk), so a single
    # backfill statement is bounded even for large knowledge bases.
    cursor.execute("UPDATE ai_document SET acl_principals = nexora_rag_acl_principals(acl_json::text)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_acl_principals "
        "ON ai_document USING GIN (acl_principals)"
    )
