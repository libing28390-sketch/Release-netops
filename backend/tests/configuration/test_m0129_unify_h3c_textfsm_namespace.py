from __future__ import annotations

import sqlite3

from database.migrations.m0129_unify_h3c_textfsm_namespace import upgrade


def test_h3c_textfsm_namespace_migration_is_canonical_and_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE platform_profiles (
                id TEXT PRIMARY KEY,
                platform_code TEXT NOT NULL,
                parser_platform TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE parser_templates (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                platform_profile_id TEXT,
                platform_code TEXT NOT NULL,
                template_code TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE devices (id TEXT PRIMARY KEY, platform TEXT);
            """
        )
        conn.executemany(
            "INSERT INTO platform_profiles (id, platform_code, parser_platform, updated_at) VALUES (?, ?, ?, '')",
            [
                ("profile-v5", "hp_comware", "hp_comware"),
                ("profile-v9", "h3c_comware9", "h3c_comware9"),
            ],
        )
        conn.executemany(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code, source_filename, updated_at)
               VALUES (?, NULL, ?, ?, ?, ?, '')""",
            [
                (
                    "template-v5",
                    "profile-v5",
                    "hp_comware",
                    "OLD_V5",
                    "hp_comware_display_bgp_peer_ipv4.textfsm",
                ),
                (
                    "template-v9",
                    "profile-v9",
                    "h3c_comware9",
                    "OLD_V9",
                    "h3c_comware9_display_bgp_peer_ipv4.textfsm",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO devices (id, platform) VALUES (?, ?)",
            [("device-v5", "hp_comware"), ("device-v9", "h3c_comware9")],
        )

        upgrade(conn, use_pg=False)
        first = [tuple(row) for row in conn.execute(
            "SELECT platform_code, source_filename, template_code FROM parser_templates ORDER BY id"
        )]
        upgrade(conn, use_pg=False)
        second = [tuple(row) for row in conn.execute(
            "SELECT platform_code, source_filename, template_code FROM parser_templates ORDER BY id"
        )]

        assert first == second
        assert first == [
            ("h3c_comware", "h3c_comware_v5_display_bgp_peer_ipv4.textfsm", "H3C_COMWARE_V5_DISPLAY_BGP_PEER_IPV4"),
            ("h3c_comware", "h3c_comware_v9_display_bgp_peer_ipv4_unicast.textfsm", "H3C_COMWARE_V9_DISPLAY_BGP_PEER_IPV4_UNICAST"),
        ]
        assert conn.execute("SELECT DISTINCT parser_platform FROM platform_profiles").fetchall() == [("h3c_comware",)]
        assert conn.execute("SELECT platform FROM devices ORDER BY id").fetchall() == [("h3c_comware",), ("h3c_comware",)]
    finally:
        conn.close()
