"""Normalize the legacy AI Provider tags JSON default/data shape."""

from __future__ import annotations

VERSION = 148
NAME = "ai_provider_tags_json_normalization"


def upgrade(cursor, use_pg: bool) -> None:
    # m0139 introduced tags_json with an object default (`{}`), while the API
    # contract is a list[str].  Only known empty/object/null legacy values are
    # rewritten; non-empty malformed values remain readable via the API's
    # fail-closed decoder and are not guessed or silently reinterpreted.
    cursor.execute(
        """
        UPDATE ai_provider
        SET tags_json = '[]'
        WHERE tags_json IS NULL
           OR TRIM(tags_json) = ''
           OR TRIM(tags_json) = '{}'
           OR LOWER(TRIM(tags_json)) = 'null'
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Data normalization is intentionally retained on rollback; restoring the
    # invalid object default would reintroduce the Provider API outage.
    return None
