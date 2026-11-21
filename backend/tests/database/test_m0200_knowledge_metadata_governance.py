from __future__ import annotations

import uuid

from psycopg2.extras import Json

from database import get_db_connection
from database.migrations import m0200_knowledge_metadata_governance as migration


def test_m0200_marks_unclassified_documents_pending_and_excludes_them_from_rag(isolated_db):
    suffix = uuid.uuid4().hex[:12]
    knowledge_base_id = f"m0200-kb-{suffix}"
    pending_id = f"m0200-pending-{suffix}"
    known_id = f"m0200-known-{suffix}"
    now = "2026-09-01T00:00:00+00:00"
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO ai_knowledge_base
                (id, name, description, enabled, created_by, created_at, tenant_id)
            VALUES (?, ?, ?, 1, ?, ?, 'tenant-default')
            """,
            (knowledge_base_id, "M0200 governance test", "Migration test fixture", "pytest", now),
        )
        conn.execute(
            """
            INSERT INTO ai_document
                (id, knowledge_base_id, name, vendor, product_family, product_series,
                 status, tenant_id, metadata_json, ingestion_status, exclude_from_rag,
                 created_at, updated_at)
            VALUES (?, ?, 'OSPF SOP', '', '', '', 'active', 'tenant-default', ?, 'ready', 0, ?, ?)
            """,
            (pending_id, knowledge_base_id, Json({"document_id": pending_id}), now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_document
                (id, knowledge_base_id, name, vendor, product_family, product_series,
                 status, tenant_id, metadata_json, ingestion_status, exclude_from_rag,
                 created_at, updated_at)
            VALUES (?, ?, 'Huawei OSPF', 'Huawei', 'campus_switch', 'S5700', 'active', 'tenant-default', ?, 'ready', 0, ?, ?)
            """,
            (known_id, knowledge_base_id, Json({"document_id": known_id}), now, now),
        )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        pending = conn.execute(
            "SELECT metadata_governance_status, metadata_governance_reason, ingestion_status, exclude_from_rag, metadata_json "
            "FROM ai_document WHERE id = ?",
            (pending_id,),
        ).fetchone()
        assert pending[0] == "pending_review"
        assert pending[1] == "missing_taxonomy_fields:vendor,product_family,product_series"
        assert pending[2] == "pending_review"
        assert pending[3] == 1
        assert pending[4]["metadata_governance_status"] == "pending_review"
        assert pending[4]["metadata_governance_reason"] == pending[1]

        known = conn.execute(
            "SELECT metadata_governance_status, metadata_governance_reason, ingestion_status, exclude_from_rag "
            "FROM ai_document WHERE id = ?",
            (known_id,),
        ).fetchone()
        assert tuple(known) == ("ready", "", "ready", 0)

        snapshot = tuple(pending)
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert tuple(conn.execute(
            "SELECT metadata_governance_status, metadata_governance_reason, ingestion_status, exclude_from_rag, metadata_json "
            "FROM ai_document WHERE id = ?",
            (pending_id,),
        ).fetchone()) == snapshot
    finally:
        conn.close()
