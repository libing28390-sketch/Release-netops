from __future__ import annotations

import hashlib
import json

from backend.tests.pg_test_utils import PostgreSQLTestConnection, postgresql_test_driver
from database.migrations import m0347_h3c_v7_bgp_vrf_route_command as migration


def _create_schema() -> PostgreSQLTestConnection:
    conn = postgresql_test_driver.connect()
    conn.executescript(
        """
        CREATE TABLE platform_profiles (
            id TEXT PRIMARY KEY,
            platform_code TEXT NOT NULL,
            source TEXT NOT NULL,
            tenant_id TEXT
        );
        CREATE TABLE platform_releases (
            id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            status TEXT NOT NULL,
            checksum TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE platform_release_actions (
            id TEXT PRIMARY KEY,
            release_id TEXT NOT NULL,
            action_code TEXT NOT NULL,
            command TEXT NOT NULL,
            parser_template_version_id TEXT,
            field_contract_json TEXT NOT NULL,
            command_checksum TEXT NOT NULL,
            updated_at TEXT
        );
        """
    )
    return conn


def _insert_release(conn, profile_id: str, release_id: str, status: str, command: str) -> None:
    conn.execute(
        "INSERT INTO platform_releases (id, profile_id, status, checksum) VALUES (?, ?, ?, '')",
        (release_id, profile_id, status),
    )
    conn.execute(
        """INSERT INTO platform_release_actions (
             id, release_id, action_code, command, field_contract_json,
             command_checksum
           ) VALUES (?, ?, 'get_bgp_routes_vrf', ?, '{}', '')""",
        (f"action-{release_id}", release_id, command),
    )


def test_migration_repairs_only_published_system_h3c_v7_route_actions_and_is_idempotent():
    conn = _create_schema()
    conn.executemany(
        "INSERT INTO platform_profiles (id, platform_code, source, tenant_id) VALUES (?, ?, ?, ?)",
        [
            ("system-v7", "h3c_comware_v7", "SYSTEM", None),
            ("system-v9", "h3c_comware_v9", "SYSTEM", None),
            ("tenant-v7", "h3c_comware_v7", "CUSTOM", "tenant-1"),
        ],
    )
    old = migration.OLD_COMMAND
    _insert_release(conn, "system-v7", "v7-published", "PUBLISHED", old)
    _insert_release(conn, "system-v7", "v7-draft", "DRAFT", old)
    _insert_release(conn, "system-v9", "v9-published", "PUBLISHED", old)
    _insert_release(conn, "tenant-v7", "tenant-published", "PUBLISHED", old)

    migration.upgrade(conn.cursor(), use_pg=True)
    first = conn.execute(
        "SELECT command, command_checksum FROM platform_release_actions WHERE id = 'action-v7-published'"
    ).fetchone()
    release = conn.execute(
        "SELECT checksum FROM platform_releases WHERE id = 'v7-published'"
    ).fetchone()
    encoded_actions = json.dumps(
        [{
            "action_code": "get_bgp_routes_vrf",
            "command": migration.NEW_COMMAND,
            "parser_template_version_id": None,
            "field_contract_json": "{}",
        }],
        ensure_ascii=False,
        sort_keys=True,
    )

    assert first["command"] == migration.NEW_COMMAND
    assert first["command_checksum"] == hashlib.sha256(
        migration.NEW_COMMAND.encode("utf-8")
    ).hexdigest()
    assert release["checksum"] == hashlib.sha256(encoded_actions.encode("utf-8")).hexdigest()
    assert conn.execute(
        "SELECT command FROM platform_release_actions WHERE id = 'action-v7-draft'"
    ).fetchone()[0] == old
    assert conn.execute(
        "SELECT command FROM platform_release_actions WHERE id = 'action-v9-published'"
    ).fetchone()[0] == old
    assert conn.execute(
        "SELECT command FROM platform_release_actions WHERE id = 'action-tenant-published'"
    ).fetchone()[0] == old

    updated_at = conn.execute(
        "SELECT updated_at FROM platform_releases WHERE id = 'v7-published'"
    ).fetchone()[0]
    migration.upgrade(conn.cursor(), use_pg=True)
    assert conn.execute(
        "SELECT updated_at FROM platform_releases WHERE id = 'v7-published'"
    ).fetchone()[0] == updated_at
