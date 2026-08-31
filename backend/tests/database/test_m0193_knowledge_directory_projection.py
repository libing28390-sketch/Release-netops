from __future__ import annotations

import json

from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0195_knowledge_directory_projection as migration


def test_m0193_backfills_missing_directory_paths_and_is_idempotent():
    connection = postgresql_test_driver.connect()
    try:
        connection.executescript(
            """
            CREATE TABLE ai_document (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                vendor TEXT,
                document_category TEXT,
                metadata_json JSONB NOT NULL
            );
            INSERT INTO ai_document (id, tenant_id, vendor, document_category, metadata_json)
            VALUES
                ('doc-command', 'tenant-a', 'H3C', 'command', '{"title":"H3C command"}'::jsonb),
                ('doc-config', 'tenant-a', 'Huawei', 'configuration', '{"title":"Huawei config"}'::jsonb),
                ('doc-missing-category', 'tenant-a', 'Cisco', NULL, '{"title":"Cisco guide"}'::jsonb),
                ('doc-custom', 'tenant-a', 'Ruijie', 'hardware', '{"knowledge_directory_path":"custom/runbook"}'::jsonb);
            """
        )

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        rows = connection.execute(
            "SELECT id, metadata_json::text FROM ai_document ORDER BY id"
        ).fetchall()
        paths = {
            row[0]: json.loads(row[1]).get("knowledge_directory_path")
            for row in rows
        }
        assert paths == {
            "doc-command": "02_commands/h3c",
            "doc-config": "03_configuration/huawei",
            "doc-custom": "custom/runbook",
            "doc-missing-category": "01_product/cisco",
        }

        snapshot = [tuple(row) for row in rows]
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        assert [tuple(row) for row in connection.execute(
            "SELECT id, metadata_json::text FROM ai_document ORDER BY id"
        ).fetchall()] == snapshot
    finally:
        connection.close()
