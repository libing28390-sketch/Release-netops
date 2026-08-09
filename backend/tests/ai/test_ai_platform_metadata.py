import json
import sqlite3

from database.migrations import m0110_repair_ai_document_platforms


def test_repairs_cross_vendor_huawei_default_and_preserves_compatible_platforms():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE physical_assets (
            vendor TEXT,
            platform TEXT,
            asset_type TEXT
        );
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            vendor TEXT,
            platform TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            metadata_json TEXT
        );
        """
    )
    cursor.executemany(
        "INSERT INTO physical_assets (vendor, platform, asset_type) VALUES (?, ?, ?)",
        [
            ("H3C", "h3c_comware", "network_device"),
            ("H3C", "hp_comware", "network_device"),
            ("Cisco", "cisco_ios", "network_device"),
            ("Huawei", "huawei_vrp", "network_device"),
        ],
    )
    cursor.executemany(
        "INSERT INTO ai_document (id, vendor, platform) VALUES (?, ?, ?)",
        [
            ("doc-h3c", "H3C", "huawei_vrp"),
            ("doc-cisco", "Cisco", "huawei_vrp"),
            ("doc-huawei", "Huawei", "huawei_vrp"),
            ("doc-h3c-compatible", "H3C", "hp_comware"),
        ],
    )
    cursor.execute(
        "INSERT INTO ai_document_chunk (id, document_id, metadata_json) VALUES (?, ?, ?)",
        ("chunk-h3c", "doc-h3c", json.dumps({"vendor": "H3C", "platform": "huawei_vrp"})),
    )

    m0110_repair_ai_document_platforms.upgrade(cursor, use_pg=False)
    conn.commit()

    rows = cursor.execute("SELECT id, platform FROM ai_document ORDER BY id").fetchall()
    assert rows == [
        ("doc-cisco", "cisco_ios"),
        ("doc-h3c", "h3c_comware"),
        ("doc-h3c-compatible", "hp_comware"),
        ("doc-huawei", "huawei_vrp"),
    ]
    chunk_metadata = json.loads(
        cursor.execute("SELECT metadata_json FROM ai_document_chunk WHERE id = 'chunk-h3c'").fetchone()[0]
    )
    assert chunk_metadata["platform"] == "h3c_comware"
