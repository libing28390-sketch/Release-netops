from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.migrations import (  # noqa: E402
    discover_migrations,
    m0342_ruijie_rgos_v10_official_samples as legacy_migration,
    m0344_archive_ruijie_rgos_v10_rsr_templates as migration,
)
from database.migrations.m0100_register_builtin_textfsm_templates import _checksum  # noqa: E402


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE platform_profiles (
            id TEXT PRIMARY KEY, platform_code TEXT, source TEXT, tenant_id TEXT
        );
        CREATE TABLE platform_releases (
            id TEXT PRIMARY KEY, profile_id TEXT, status TEXT,
            checksum TEXT, updated_at TEXT
        );
        CREATE TABLE platform_release_actions (
            id TEXT PRIMARY KEY, release_id TEXT, action_code TEXT, command TEXT,
            parser_template_version_id TEXT, field_contract_json TEXT,
            command_checksum TEXT, updated_at TEXT
        );
        CREATE TABLE parser_templates (
            id TEXT PRIMARY KEY, tenant_id TEXT, platform_profile_id TEXT,
            platform_code TEXT, source_filename TEXT, source TEXT,
            status TEXT, updated_at TEXT
        );
        CREATE TABLE parser_template_versions (
            id TEXT PRIMARY KEY, template_id TEXT, status TEXT, updated_at TEXT
        );
        """
    )
    return conn


def _release_checksum(conn: sqlite3.Connection, release_id: str) -> str:
    actions = [
        dict(row)
        for row in conn.execute(
            """SELECT action_code, command, parser_template_version_id, field_contract_json
               FROM platform_release_actions WHERE release_id = ? ORDER BY action_code""",
            (release_id,),
        ).fetchall()
    ]
    return _checksum(actions)


def test_legacy_342_marker_is_a_noop_and_migration_chain_stays_ordered():
    class NoQueryCursor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("the compatibility marker must not write migration data")

    legacy_migration.upgrade(NoQueryCursor(), use_pg=True)
    versions = [int(module.VERSION) for module in discover_migrations()]
    assert versions == sorted(versions)
    assert 342 in versions
    assert 343 in versions
    assert migration.VERSION == 344


def test_m0344_archives_only_legacy_rsr_rows_and_clears_exact_version_bindings():
    conn = _connection()
    v10_profile = "system-profile-ruijie_rgos_v10"
    h3c_profile = "system-profile-h3c_comware_v9"
    v11_profile = "system-profile-ruijie_rgos_v11"
    v12_profile = "system-profile-ruijie_rgos_v12"
    tenant_profile = "custom-profile-ruijie-rgos-v10"
    conn.executemany(
        "INSERT INTO platform_profiles VALUES (?, ?, ?, ?)",
        [
            (v10_profile, "ruijie_rgos_v10", "SYSTEM", None),
            (h3c_profile, "h3c_comware_v9", "SYSTEM", None),
            (v11_profile, "ruijie_rgos_v11", "SYSTEM", None),
            (v12_profile, "ruijie_rgos_v12", "SYSTEM", None),
            (tenant_profile, "ruijie_rgos_v10", "CUSTOM", "tenant-1"),
        ],
    )
    conn.executemany(
        "INSERT INTO platform_releases VALUES (?, ?, ?, ?, ?)",
        [
            ("v10-current", v10_profile, "PUBLISHED", "old-current", "old"),
            ("v10-draft", v10_profile, "DRAFT", "old-draft", "old"),
            ("h3c-current", h3c_profile, "PUBLISHED", "keep-h3c", "old"),
            ("v11-current", v11_profile, "PUBLISHED", "keep-v11", "old"),
            ("v12-current", v12_profile, "PUBLISHED", "keep-v12", "old"),
            ("tenant-release", tenant_profile, "DRAFT", "keep-tenant", "old"),
        ],
    )

    for filename in migration.TEMPLATE_FILENAMES:
        template_id, version_id = migration._template_ids(filename)
        conn.execute(
            "INSERT INTO parser_templates VALUES (?, NULL, ?, 'ruijie_rgos', ?, 'SYSTEM', 'ACTIVE', 'old')",
            (template_id, v10_profile, filename),
        )
        conn.execute(
            "INSERT INTO parser_template_versions VALUES (?, ?, 'PUBLISHED', 'old')",
            (version_id, template_id),
        )

    # Similar names outside the exact old SYSTEM rows must remain available.
    conn.execute(
        """INSERT INTO parser_templates VALUES
           ('tenant-template', 'tenant-1', ?, 'ruijie_rgos',
            'ruijie_rgos_v10_show_memory.textfsm', 'CUSTOM', 'ACTIVE', 'old')""",
        (v10_profile,),
    )
    conn.execute(
        """INSERT INTO parser_template_versions VALUES
           ('tenant-version', 'tenant-template', 'PUBLISHED', 'old')"""
    )
    conn.execute(
        """INSERT INTO parser_templates VALUES
           ('unrelated-v10-template', NULL, ?, 'ruijie_rgos',
            'ruijie_rgos_v10_show_version.textfsm', 'SYSTEM', 'ACTIVE', 'old')""",
        (v10_profile,),
    )
    conn.execute(
        """INSERT INTO parser_template_versions VALUES
           ('unrelated-v10-version', 'unrelated-v10-template', 'PUBLISHED', 'old')"""
    )
    conn.executemany(
        """INSERT INTO parser_templates VALUES (?, NULL, ?, 'ruijie_rgos', ?,
           'SYSTEM', 'ACTIVE', 'old')""",
        [
            ("ruijie-v11-template", v11_profile, "ruijie_rgos_v11_show_memory.textfsm"),
            ("ruijie-v12-template", v12_profile, "ruijie_rgos_v12_show_memory.textfsm"),
        ],
    )
    conn.executemany(
        "INSERT INTO parser_template_versions VALUES (?, ?, 'PUBLISHED', 'old')",
        [
            ("ruijie-v11-version", "ruijie-v11-template"),
            ("ruijie-v12-version", "ruijie-v12-template"),
        ],
    )

    bound_action_ids = []
    system_memory_version = ""
    for action_code, filename in (
        ("get_memory", "ruijie_rgos_v10_show_memory.textfsm"),
        ("get_route_table", "ruijie_rgos_v10_show_ip_route.textfsm"),
        ("get_clock", "ruijie_rgos_v10_show_clock.textfsm"),
    ):
        _template_id, version_id = migration._template_ids(filename)
        if action_code == "get_memory":
            system_memory_version = version_id
        for release_id in ("v10-current", "v10-draft"):
            action_id = f"{release_id}-{action_code}"
            bound_action_ids.append(action_id)
            conn.execute(
                """INSERT INTO platform_release_actions VALUES
                   (?, ?, ?, ?, ?, '{}', 'command-checksum', 'old')""",
                (action_id, release_id, action_code, "sample command", version_id),
            )
    conn.execute(
        """INSERT INTO platform_release_actions VALUES
           ('tenant-memory-action', 'tenant-release', 'get_memory', 'show memory',
            ?, '{}', 'tenant-command-checksum', 'old')""",
        (system_memory_version,),
    )
    conn.execute(
        """INSERT INTO platform_release_actions VALUES
           ('keep-h3c-action', 'h3c-current', 'get_clock', 'display clock',
            'h3c-v9-version', '{}', 'h3c-command-checksum', 'old')"""
    )
    conn.executemany(
        """INSERT INTO platform_release_actions VALUES
           (?, ?, 'get_memory', 'show memory', ?, '{}', ?, 'old')""",
        [
            ("keep-v11-action", "v11-current", "ruijie-v11-version", "v11-command-checksum"),
            ("keep-v12-action", "v12-current", "ruijie-v12-version", "v12-command-checksum"),
        ],
    )
    conn.execute(
        """INSERT INTO platform_release_actions VALUES
           ('keep-other-v10-action', 'v10-current', 'get_version', 'show version',
            'unrelated-v10-version', '{}', 'version-command-checksum', 'old')"""
    )
    conn.commit()

    migration.upgrade(conn.cursor(), use_pg=True)
    conn.commit()

    for filename in migration.TEMPLATE_FILENAMES:
        template_id, version_id = migration._template_ids(filename)
        template = conn.execute(
            "SELECT status FROM parser_templates WHERE id = ?", (template_id,)
        ).fetchone()
        version = conn.execute(
            "SELECT status FROM parser_template_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if filename == "ruijie_rgos_v10_show_memory.textfsm":
            assert template[0] == "ACTIVE"
            assert version[0] == "PUBLISHED"
        else:
            assert template[0] == "ARCHIVED"
            assert version[0] == "ARCHIVED"

    assert all(
        conn.execute(
            "SELECT parser_template_version_id FROM platform_release_actions WHERE id = ?",
            (action_id,),
        ).fetchone()[0] is None
        for action_id in bound_action_ids
    )
    assert conn.execute(
        "SELECT status FROM parser_templates WHERE id = 'tenant-template'"
    ).fetchone()[0] == "ACTIVE"
    assert conn.execute(
        "SELECT status FROM parser_template_versions WHERE id = 'tenant-version'"
    ).fetchone()[0] == "PUBLISHED"
    assert conn.execute(
        "SELECT status FROM parser_templates WHERE id = 'unrelated-v10-template'"
    ).fetchone()[0] == "ACTIVE"
    assert conn.execute(
        "SELECT parser_template_version_id FROM platform_release_actions WHERE id = 'keep-h3c-action'"
    ).fetchone()[0] == "h3c-v9-version"
    assert conn.execute(
        "SELECT parser_template_version_id FROM platform_release_actions WHERE id = 'keep-other-v10-action'"
    ).fetchone()[0] == "unrelated-v10-version"
    assert conn.execute(
        "SELECT parser_template_version_id FROM platform_release_actions WHERE id = 'tenant-memory-action'"
    ).fetchone()[0] == system_memory_version
    assert conn.execute(
        "SELECT checksum FROM platform_releases WHERE id = 'tenant-release'"
    ).fetchone()[0] == "keep-tenant"
    for release_id in ("v10-current", "v10-draft"):
        assert conn.execute(
            "SELECT checksum FROM platform_releases WHERE id = ?", (release_id,)
        ).fetchone()[0] == _release_checksum(conn, release_id)
    assert conn.execute(
        "SELECT checksum FROM platform_releases WHERE id = 'h3c-current'"
    ).fetchone()[0] == "keep-h3c"
    assert conn.execute(
        "SELECT status FROM parser_templates WHERE id = 'ruijie-v11-template'"
    ).fetchone()[0] == "ACTIVE"
    assert conn.execute(
        "SELECT status FROM parser_templates WHERE id = 'ruijie-v12-template'"
    ).fetchone()[0] == "ACTIVE"
    assert conn.execute(
        "SELECT parser_template_version_id FROM platform_release_actions WHERE id = 'keep-v11-action'"
    ).fetchone()[0] == "ruijie-v11-version"
    assert conn.execute(
        "SELECT parser_template_version_id FROM platform_release_actions WHERE id = 'keep-v12-action'"
    ).fetchone()[0] == "ruijie-v12-version"

    state_before_repeat = (
        conn.execute("SELECT id, status, updated_at FROM parser_templates ORDER BY id").fetchall(),
        conn.execute("SELECT id, status, updated_at FROM parser_template_versions ORDER BY id").fetchall(),
        conn.execute("SELECT id, checksum, updated_at FROM platform_releases ORDER BY id").fetchall(),
    )
    migration.upgrade(conn.cursor(), use_pg=True)
    conn.commit()
    state_after_repeat = (
        conn.execute("SELECT id, status, updated_at FROM parser_templates ORDER BY id").fetchall(),
        conn.execute("SELECT id, status, updated_at FROM parser_template_versions ORDER BY id").fetchall(),
        conn.execute("SELECT id, checksum, updated_at FROM platform_releases ORDER BY id").fetchall(),
    )
    assert state_after_repeat == state_before_repeat
    conn.close()
