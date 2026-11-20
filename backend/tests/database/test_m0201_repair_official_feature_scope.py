from __future__ import annotations

import uuid

from psycopg2.extras import Json

from database import get_db_connection
from database.migrations import m0201_repair_official_feature_scope as migration


def test_m0201_clears_unreviewed_body_inferred_scope_for_all_vendors(isolated_db):
    suffix = uuid.uuid4().hex[:12]
    knowledge_base_id = f"m0201-kb-{suffix}"
    now = "2026-09-01T00:00:00+00:00"
    documents = {
        "cisco": {
            "id": f"m0201-cisco-{suffix}",
            "name": "Catalyst System Management Command Reference",
            "source": "https://www.cisco.com/c/en/system_management_commands.html",
            "vendor": "Cisco",
        },
        "h3c": {
            "id": f"m0201-h3c-{suffix}",
            "name": "H3C S6300 Troubleshooting Guide",
            "source": "https://www.h3c.com/cn/troubleshooting/s6300.htm",
            "vendor": "H3C",
        },
        "explicit": {
            "id": f"m0201-explicit-{suffix}",
            "name": "Vendor Command Reference",
            "source": "https://docs.example.test/commands.html",
            "vendor": "Huawei",
        },
    }
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO ai_knowledge_base
                (id, name, description, enabled, created_by, created_at, tenant_id)
            VALUES (?, ?, ?, 1, ?, ?, 'tenant-default')
            """,
            (knowledge_base_id, "M0201 feature scope test", "Migration test fixture", "pytest", now),
        )
        for kind, document in documents.items():
            metadata = {
                "title": document["name"],
                "source_type": "official_url",
                "source_kind": "command_reference" if kind != "h3c" else "troubleshooting_guide",
                "feature": "vlan",
                "feature_domain": "switching",
            }
            if kind == "explicit":
                metadata["feature_source"] = "explicit"
            conn.execute(
                """
                INSERT INTO ai_document
                    (id, knowledge_base_id, name, source, vendor, platform,
                     status, created_at, updated_at, tenant_id, source_trust_level,
                     knowledge_source_type, metadata_json, document_category,
                     cli_platform, feature_domain, feature, exclude_from_rag)
                VALUES (?, ?, ?, ?, ?, 'vendor-cli', 'active', ?, ?,
                        'tenant-default', 'official', 'official_url', ?,
                        'command', 'vendor-cli', 'switching', 'vlan', 0)
                """,
                (
                    document["id"],
                    knowledge_base_id,
                    document["name"],
                    document["source"],
                    document["vendor"],
                    now,
                    now,
                    Json(metadata),
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_document_chunk
                    (id, document_id, content, metadata_json, section, created_at,
                     is_retrieval_candidate, feature_domain, feature)
                VALUES (?, ?, ?, ?, 'unrelated section', ?, 1, 'switching', 'vlan')
                """,
                (
                    f"chunk-{kind}-{suffix}",
                    document["id"],
                    "show license tech support\nSmartAgent status",
                    Json(metadata),
                    now,
                ),
            )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        repaired = conn.execute(
            """
            SELECT id, feature, feature_domain, metadata_json
            FROM ai_document
            WHERE id IN (?, ?, ?)
            ORDER BY id
            """,
            tuple(document["id"] for document in documents.values()),
        ).fetchall()
        by_id = {row[0]: row for row in repaired}
        for kind in ("cisco", "h3c"):
            row = by_id[documents[kind]["id"]]
            assert row[1] is None
            assert row[2] == "general"
            assert row[3]["feature_source"] == "unclassified"
            assert row[3]["feature_repair"] == "legacy_body_inference_cleared"
            assert "feature" not in row[3]

        explicit = by_id[documents["explicit"]["id"]]
        assert explicit[1] == "vlan"
        assert explicit[2] == "switching"
        assert explicit[3]["feature_source"] == "explicit"

        chunks = conn.execute(
            """
            SELECT document_id, feature, feature_domain, metadata_json
            FROM ai_document_chunk
            WHERE document_id IN (?, ?, ?)
            ORDER BY document_id
            """,
            tuple(document["id"] for document in documents.values()),
        ).fetchall()
        chunks_by_id = {row[0]: row for row in chunks}
        assert list(chunks_by_id[documents["cisco"]["id"]][1:3]) == [None, "general"]
        assert list(chunks_by_id[documents["h3c"]["id"]][1:3]) == [None, "general"]
        assert list(chunks_by_id[documents["explicit"]["id"]][1:3]) == ["vlan", "switching"]

        snapshot = [tuple(row) for row in repaired]
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert [
            tuple(row)
            for row in conn.execute(
                """
                SELECT id, feature, feature_domain, metadata_json
                FROM ai_document
                WHERE id IN (?, ?, ?)
                ORDER BY id
                """,
                tuple(document["id"] for document in documents.values()),
            ).fetchall()
        ] == snapshot
    finally:
        conn.close()
