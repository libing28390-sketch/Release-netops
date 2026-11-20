import json
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0161_classify_official_huawei_registry import upgrade


def test_m0161_moves_only_verified_huawei_registry_rows_into_official_scope():
    conn = postgresql_test_driver.connect()
    conn.execute(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            vendor TEXT,
            source TEXT,
            knowledge_source_type TEXT,
            metadata_json TEXT
        )
        """
    )
    official_metadata = {
        "document_type": "hardware_manual",
        "source_type": "official",
        "official_only": True,
        "sources": [{"source_url": "https://info.support.huawei.com/official"}],
    }
    conn.execute(
        "INSERT INTO ai_document VALUES (?, ?, ?, ?, ?)",
        ("official", "Huawei", "upload", "user_document", json.dumps(official_metadata)),
    )
    conn.execute(
        "INSERT INTO ai_document VALUES (?, ?, ?, ?, ?)",
        ("enterprise", "Huawei", "upload", "user_document", json.dumps({"document_type": "hardware_manual"})),
    )

    upgrade(conn, use_pg=True)
    upgrade(conn, use_pg=True)

    official = conn.execute(
        "SELECT source, knowledge_source_type FROM ai_document WHERE id = 'official'"
    ).fetchone()
    enterprise = conn.execute(
        "SELECT source, knowledge_source_type FROM ai_document WHERE id = 'enterprise'"
    ).fetchone()
    conn.close()

    assert tuple(official) == ("https://info.support.huawei.com/official", "official_url")
    assert tuple(enterprise) == ("upload", "user_document")
