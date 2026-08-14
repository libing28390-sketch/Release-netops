from __future__ import annotations

import hashlib
import sqlite3

from database.migrations.m0136_stabilize_librenms_source_identity import upgrade


def _stable_source_id() -> str:
    value = "librenms\0librenms\0catalog".encode("utf-8")
    return f"source-{hashlib.sha256(value).hexdigest()[:24]}"


def test_m0136_rekeys_and_retires_duplicate_active_paths() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE snmp_mibs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            vendor TEXT NOT NULL,
            filename TEXT NOT NULL,
            node_count INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            relative_path TEXT NOT NULL DEFAULT '',
            parse_status TEXT NOT NULL DEFAULT 'legacy',
            is_active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_nodes (
            id TEXT PRIMARY KEY,
            mib_id TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_import_items (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            mib_id TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO snmp_mibs "
        "(id, name, vendor, filename, node_count, source_type, source_id, relative_path, parse_status, is_active, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'librenms', ?, ?, ?, 1, ?)",
        [
            ("old", "SAME-MIB", "Huawei", "SAME-MIB", 10, "source-old", "huawei/SAME-MIB", "parsed", "2026-08-13T00:00:00+00:00"),
            ("new", "SAME-MIB", "Huawei", "SAME-MIB", 8, "source-new", "huawei/SAME-MIB", "parsed", "2026-08-14T00:00:00+00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO snmp_mib_import_items (id, source_id, mib_id) VALUES (?, ?, ?)",
        [("item-old", "source-old", "old"), ("item-new", "source-new", "new")],
    )

    upgrade(conn.cursor(), use_pg=False)
    conn.commit()

    stable_id = _stable_source_id()
    assert conn.execute(
        "SELECT id, source_id, is_active FROM snmp_mibs ORDER BY id"
    ).fetchall() == [("new", stable_id, 1), ("old", stable_id, 0)]
    assert conn.execute(
        "SELECT mib_id FROM snmp_mib_import_items ORDER BY id"
    ).fetchall() == [("new",), ("new",)]
    index_names = {
        row[1] for row in conn.execute("PRAGMA index_list('snmp_mibs')").fetchall()
    }
    assert "idx_snmp_mibs_librenms_path" in index_names
    conn.close()
