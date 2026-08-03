import sqlite3

from database.migrations.m0095_seed_core_platform_identification_rules import RULES, upgrade


def test_core_platform_identification_migration_is_idempotent_and_driver_specific() -> None:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE platform_profiles (
                 id TEXT PRIMARY KEY, tenant_id TEXT, source TEXT, platform_code TEXT
               )"""
        )
        conn.execute(
            """CREATE TABLE platform_identification_rules (
                 id TEXT PRIMARY KEY, platform_profile_id TEXT, command TEXT,
                 match_type TEXT, pattern TEXT, logic_group TEXT, rule_order INTEGER,
                 confidence REAL, negate INTEGER, enabled INTEGER, created_at TEXT
               )"""
        )
        conn.executemany(
            "INSERT INTO platform_profiles (id, tenant_id, source, platform_code) VALUES (?, NULL, 'SYSTEM', ?)",
            [(f'profile-{code}', code) for code in RULES],
        )

        upgrade(conn, use_pg=False)
        first_count = conn.execute('SELECT COUNT(*) FROM platform_identification_rules').fetchone()[0]
        upgrade(conn, use_pg=False)
        second_count = conn.execute('SELECT COUNT(*) FROM platform_identification_rules').fetchone()[0]

        assert first_count == second_count == sum(len(patterns) for _, patterns in RULES.values())
        assert conn.execute(
            """SELECT command FROM platform_identification_rules r
               JOIN platform_profiles p ON p.id = r.platform_profile_id
               WHERE p.platform_code = 'cisco_ios'"""
        ).fetchone()[0] == 'show version'
        assert conn.execute(
            """SELECT command FROM platform_identification_rules r
               JOIN platform_profiles p ON p.id = r.platform_profile_id
               WHERE p.platform_code = 'huawei_vrp'"""
        ).fetchone()[0] == 'display version'
    finally:
        conn.close()
