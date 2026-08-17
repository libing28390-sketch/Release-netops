"""Transactional PostgreSQL probe for the provider-tags normalization migration."""

from __future__ import annotations

import database.core as database_core
from database.migrations import m0148_ai_provider_tags_json_normalization as migration


def main() -> None:
    if not database_core._USE_PG:
        raise SystemExit("m0148 PostgreSQL probe requires the configured PostgreSQL authority")
    connection = database_core.get_db_connection()
    try:
        connection.execute(
            "CREATE TEMP TABLE ai_provider (id TEXT PRIMARY KEY, tags_json TEXT) ON COMMIT DROP"
        )
        connection.execute(
            "INSERT INTO ai_provider (id, tags_json) VALUES (?, ?), (?, ?), (?, ?)",
            ("legacy", "{}", "null", "null", "valid", '["network"]'),
        )
        migration.upgrade(connection.cursor(), use_pg=True)
        rows = dict(connection.execute("SELECT id, tags_json FROM ai_provider").fetchall())
        assert rows == {"legacy": "[]", "null": "[]", "valid": '["network"]'}
        connection.rollback()
        print('{"status":"PASS","backend":"postgresql","rolled_back":true}')
    finally:
        connection.close()


if __name__ == "__main__":
    main()
