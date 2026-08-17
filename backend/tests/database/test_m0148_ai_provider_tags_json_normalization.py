from __future__ import annotations

import sqlite3

from database.migrations import m0148_ai_provider_tags_json_normalization as migration


def test_m0148_normalizes_known_legacy_values_and_is_idempotent():
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE ai_provider (id TEXT PRIMARY KEY, tags_json TEXT)")
    cursor.executemany(
        "INSERT INTO ai_provider (id, tags_json) VALUES (?, ?)",
        [("empty", "{}"), ("null", "null"), ("blank", ""), ("valid", '["network"]')],
    )

    migration.upgrade(cursor, use_pg=False)
    migration.upgrade(cursor, use_pg=False)
    rows = dict(cursor.execute("SELECT id, tags_json FROM ai_provider").fetchall())

    assert rows == {
        "empty": "[]",
        "null": "[]",
        "blank": "[]",
        "valid": '["network"]',
    }
