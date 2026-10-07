"""Allow the governed troubleshooting-guide source kind in the V2 registry.

The source registry was created before ``troubleshooting_guide`` became a
first-class official document type.  PostgreSQL therefore still enforced the
old CHECK constraint and rejected otherwise valid H3C/Ruijie catalog imports.
This migration changes only that constraint and preserves every source fact.
"""

from __future__ import annotations


VERSION = 188
NAME = "knowledge_v2_troubleshooting_source_kind"


_SOURCE_KINDS = (
    "'official_url','product_page','configuration_guide','command_reference',"
    "'release_note','troubleshooting_guide','product_support','enterprise',"
    "'internal','user_upload','api'"
)
def _upgrade_postgres(cursor) -> None:
    cursor.execute(
        "ALTER TABLE kb_source_registry "
        "DROP CONSTRAINT IF EXISTS kb_source_registry_source_kind_check"
    )
    cursor.execute(
        "ALTER TABLE kb_source_registry "
        "ADD CONSTRAINT kb_source_registry_source_kind_check "
        f"CHECK (source_kind IN ({_SOURCE_KINDS}))"
    )

def upgrade(cursor, use_pg: bool) -> None:
    _upgrade_postgres(cursor)


def downgrade(cursor, use_pg: bool) -> None:
    # Removing this accepted kind would make already-imported source rows
    # invalid.  Keep the migration forward-compatible and non-destructive.
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
