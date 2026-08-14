from __future__ import annotations

import sqlite3

from database.migrations.m0135_deduplicate_snmp_mibs import upgrade


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE snmp_mibs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            vendor TEXT NOT NULL,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL DEFAULT '',
            node_count INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_nodes (
            id TEXT PRIMARY KEY,
            mib_id TEXT NOT NULL,
            node_name TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_import_items (
            id TEXT PRIMARY KEY,
            mib_id TEXT NOT NULL
        );
        """
    )


def test_m0135_keeps_preferred_exact_copy_and_repoints_import_items() -> None:
    conn = sqlite3.connect(":memory:")
    _create_schema(conn)
    conn.executemany(
        "INSERT INTO snmp_mibs "
        "(id, name, vendor, filename, sha256, node_count, source_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("builtin-old", "RUIJIE-DEVICE-MIB", "Ruijie", "RUIJIE-DEVICE-MIB.mib", "same", 3, "builtin", "1", "1"),
            ("builtin-new", "RUIJIE-DEVICE-MIB", "Ruijie", "RUIJIE-DEVICE-MIB.mib", "same", 3, "builtin", "2", "2"),
            ("librenms", "RUIJIE-DEVICE-MIB", "Ruijie", "RUIJIE-DEVICE-MIB.mib", "same", 3, "librenms", "3", "3"),
            ("legacy-a", "OTHER-MIB", "Vendor", "OTHER-MIB", "", 1, "builtin", "1", "1"),
            ("legacy-b", "OTHER-MIB", "Vendor", "OTHER-MIB", "", 2, "builtin", "2", "2"),
        ],
    )
    conn.executemany(
        "INSERT INTO snmp_mib_nodes (id, mib_id, node_name) VALUES (?, ?, ?)",
        [
            ("node-old", "builtin-old", "old"),
            ("node-new", "builtin-new", "new"),
            ("node-lib", "librenms", "librenms"),
            ("node-legacy-a", "legacy-a", "a"),
            ("node-legacy-b", "legacy-b", "b"),
        ],
    )
    conn.execute("INSERT INTO snmp_mib_import_items (id, mib_id) VALUES ('item-old', 'builtin-old')")

    upgrade(conn.cursor(), use_pg=False)
    conn.commit()

    rows = conn.execute(
        "SELECT id, source_type FROM snmp_mibs ORDER BY id"
    ).fetchall()
    assert rows == [("legacy-b", "builtin"), ("librenms", "librenms")]
    assert conn.execute("SELECT mib_id FROM snmp_mib_import_items WHERE id = 'item-old'").fetchone()[0] == "librenms"
    assert conn.execute("SELECT id FROM snmp_mib_nodes ORDER BY id").fetchall() == [
        ("node-legacy-b",),
        ("node-lib",),
    ]

    duplicate_builtin = (
        "builtin-extra", "OTHER-MIB", "Vendor", "OTHER-MIB", "", 1, "builtin", "4", "4"
    )
    try:
        conn.execute(
            "INSERT INTO snmp_mibs "
            "(id, name, vendor, filename, sha256, node_count, source_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            duplicate_builtin,
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("builtin identity index allowed a duplicate row")
    conn.close()
