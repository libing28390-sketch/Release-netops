from __future__ import annotations

import uuid

from psycopg2.extras import Json

from database import get_db_connection
from database.migrations import m0198_knowledge_directory_projection_repair as migration


def test_m0198_repairs_rows_created_after_the_original_projection_migration(isolated_db):
    suffix = uuid.uuid4().hex[:12]
    document_ids = {
        "config": f"m0198-config-{suffix}",
        "custom": f"m0198-custom-{suffix}",
        "empty": f"m0198-empty-{suffix}",
    }
    conn = get_db_connection()
    try:
        knowledge_base_id = f"m0198-kb-{suffix}"
        conn.execute(
            """
            INSERT INTO ai_knowledge_base
                (id, name, description, enabled, created_by, created_at, tenant_id)
            VALUES (?, ?, ?, 1, ?, ?, 'tenant-default')
            """,
            (knowledge_base_id, "M0198 test knowledge base", "Migration test fixture", "pytest", "2026-09-01T00:00:00+00:00"),
        )
        conn.commit()
        knowledge_base = conn.execute(
            "SELECT id FROM ai_knowledge_base WHERE id = ?",
            (knowledge_base_id,),
        ).fetchone()
        assert knowledge_base

        now = "2026-09-01T00:00:00+00:00"
        rows = (
            (document_ids["config"], "Huawei", "configuration", Json({"title": "Huawei config"})),
            (document_ids["custom"], "H3C", "hardware", Json({"knowledge_directory_path": "custom/runbook"})),
            (document_ids["empty"], None, None, Json({})),
        )
        for document_id, vendor, category, metadata in rows:
            conn.execute(
                """
                INSERT INTO ai_document
                    (id, knowledge_base_id, name, vendor, document_category,
                     status, created_at, updated_at, tenant_id, metadata_json)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'tenant-default', ?)
                """,
                (document_id, knowledge_base[0], document_id, vendor, category, now, now, metadata),
            )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        rows_after_first_run = conn.execute(
            "SELECT id, metadata_json FROM ai_document WHERE id IN (?, ?, ?) ORDER BY id",
            tuple(document_ids.values()),
        ).fetchall()
        paths = {
            row[0]: (row[1] or {}).get("knowledge_directory_path")
            for row in rows_after_first_run
        }
        assert paths == {
            document_ids["config"]: "03_configuration/huawei",
            document_ids["custom"]: "custom/runbook",
            document_ids["empty"]: "01_product",
        }

        snapshot = [tuple(row) for row in rows_after_first_run]
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert [tuple(row) for row in conn.execute(
            "SELECT id, metadata_json FROM ai_document WHERE id IN (?, ?, ?) ORDER BY id",
            tuple(document_ids.values()),
        ).fetchall()] == snapshot
    finally:
        conn.close()
