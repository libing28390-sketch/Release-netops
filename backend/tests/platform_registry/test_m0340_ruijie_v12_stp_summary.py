import hashlib
import json
import sqlite3

from database.migrations import m0340_ruijie_v12_stp_summary as migration
from services.platform_registry_service import get_profile_action_commands


def test_upgrades_only_unbound_default_stp_actions_in_current_v12_system_releases():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE platform_profiles (
                platform_code TEXT, source TEXT, tenant_id TEXT, status TEXT, current_release_id TEXT
            );
            CREATE TABLE platform_releases (id TEXT, status TEXT, checksum TEXT, updated_at TEXT);
            CREATE TABLE platform_release_actions (
                id TEXT, release_id TEXT, action_code TEXT, command TEXT, parser_template_version_id TEXT,
                field_contract_json TEXT, command_checksum TEXT, updated_at TEXT
            );
            """
        )
        old, new = migration.OLD_COMMAND, migration.NEW_COMMAND
        cases = [
            ("v12", "ruijie_rgos_v12", "SYSTEM", None, "PUBLISHED", old, None, True),
            ("s6k", "ruijie_s6k_rgos12", "SYSTEM", None, "PUBLISHED", old, None, False),
            ("v11", "ruijie_rgos_v11", "SYSTEM", None, "PUBLISHED", old, None, False),
            ("draft", "ruijie_rgos_v12", "SYSTEM", None, "DRAFT", old, None, False),
            ("tenant", "ruijie_rgos_v12", "CUSTOM", "tenant", "PUBLISHED", old, None, False),
            ("custom", "ruijie_rgos_v12", "SYSTEM", None, "PUBLISHED", old + " mst 0", None, False),
            ("pinned", "ruijie_rgos_v12", "SYSTEM", None, "PUBLISHED", old, "custom-parser", False),
        ]
        for release_id, profile, source, tenant, status, command, parser_id, _ in cases:
            conn.execute("INSERT INTO platform_profiles VALUES (?, ?, ?, 'ACTIVE', ?)", (profile, source, tenant, release_id))
            conn.execute("INSERT INTO platform_releases VALUES (?, ?, '', '')", (release_id, status))
            conn.execute(
                "INSERT INTO platform_release_actions VALUES (?, ?, 'get_stp', ?, ?, '{}', '', '')",
                (release_id, release_id, command, parser_id),
            )
        conn.execute("INSERT INTO platform_releases VALUES ('superseded', 'PUBLISHED', '', '')")
        conn.execute(
            "INSERT INTO platform_release_actions VALUES ('superseded', 'superseded', 'get_stp', ?, NULL, '{}', '', '')",
            (old,),
        )

        migration.upgrade(conn.cursor(), use_pg=False)
        first = conn.execute("SELECT * FROM platform_release_actions ORDER BY id").fetchall()
        migration.upgrade(conn.cursor(), use_pg=False)
        assert conn.execute("SELECT * FROM platform_release_actions ORDER BY id").fetchall() == first

        results = {row["id"]: row for row in first}
        assert results["superseded"]["command"] == old
        for release_id, _, _, _, _, command, _, changed in cases:
            result = results[release_id]
            assert result["command"] == (new if changed else command)
            if changed:
                assert result["command_checksum"] == hashlib.sha256(new.encode()).hexdigest()
                content = json.dumps(
                    [{"action_code": "get_stp", "command": new, "parser_template_version_id": None, "field_contract_json": "{}"}],
                    sort_keys=True,
                )
                checksum = conn.execute("SELECT checksum FROM platform_releases WHERE id = ?", (release_id,)).fetchone()[0]
                assert checksum == hashlib.sha256(content.encode()).hexdigest()


def test_fresh_catalog_uses_summary_only_for_explicitly_verified_ruijie_profiles():
    for profile, command in (
        ("ruijie_rgos_v12", migration.NEW_COMMAND),
        ("ruijie_s6k_rgos12", migration.OLD_COMMAND),
        ("ruijie_rgos_v11", migration.NEW_COMMAND),
    ):
        assert get_profile_action_commands({"platform_code": profile, "parser_platform": "ruijie_rgos"})["get_stp"] == command
