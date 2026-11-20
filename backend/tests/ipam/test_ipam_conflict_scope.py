from __future__ import annotations

import uuid

from database import get_db_connection, schema as database_schema
from database.migrations import run_migrations
import database.migrations.m0320_ipam_address_space_unique_index_bootstrap as m0320_migration
from database.migrations.m0320_ipam_address_space_unique_index_bootstrap import (
    upgrade as upgrade_ipam_address_space_index,
)
from services.ipam_address_space_service import create_address_space
from services.ipam_service import create_address, create_subnet, detect_conflicts


def _space(label: str) -> dict:
    return create_address_space(
        name=f"Conflict scope {label} {uuid.uuid4().hex[:8]}",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )


def test_bootstrap_keeps_duplicate_host_addresses_isolated_by_address_space(isolated_db):
    del isolated_db
    first_space = _space("first")
    second_space = _space("second")
    first_prefix = create_subnet(
        prefix="10.249.0.0/24", address_space_id=first_space["id"],
    )
    second_prefix = create_subnet(
        prefix="10.249.0.0/24", address_space_id=second_space["id"],
    )

    with get_db_connection() as conn:
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_addresses_scope_active
                 ON ip_addresses(tenant_id, vrf_id, address_inet)
                 WHERE address_inet IS NOT NULL
                   AND COALESCE(status, 'active') NOT IN ('released', 'available')"""
        )
        upgrade_ipam_address_space_index(conn.cursor(), True)
        upgrade_ipam_address_space_index(conn.cursor(), True)
        database_schema._init_db_logic(conn, allow_legacy_import=False)
        conn.commit()

        indexes = {
            row["indexname"] for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'ip_addresses'"
            ).fetchall()
        }
        assert "uq_ip_addresses_scope_active" not in indexes
        assert "uq_ip_addresses_space_active" in indexes
        assert "uq_ip_addresses_legacy_scope_active" in indexes
        foreign_keys = conn.execute(
            """SELECT COUNT(*) AS count
                 FROM pg_constraint
                WHERE conrelid = 'ip_addresses'::regclass
                  AND confrelid = 'ipam_address_spaces'::regclass"""
        ).fetchone()["count"]
        assert foreign_keys >= 1

    first = create_address(first_prefix["id"], address="10.249.0.10")
    second = create_address(second_prefix["id"], address="10.249.0.10")
    assert first["address"] == second["address"] == "10.249.0.10"
    with get_db_connection() as conn:
        scopes = {
            row["address_space_id"]
            for row in conn.execute(
                "SELECT id, address_space_id FROM ip_addresses WHERE id IN (?, ?)",
                (first["id"], second["id"]),
            ).fetchall()
        }
    assert scopes == {first_space["id"], second_space["id"]}
    assert detect_conflicts()["ip_conflicts"] == []


def test_m0320_adjacent_upgrade_failure_rolls_back_and_retry_is_idempotent(
    isolated_db, monkeypatch,
):
    del isolated_db
    with get_db_connection() as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", (m0320_migration.VERSION,))
        conn.execute(
            """CREATE UNIQUE INDEX uq_ip_addresses_scope_active
                 ON ip_addresses(tenant_id, vrf_id, address_inet)
                WHERE address_inet IS NOT NULL
                  AND COALESCE(status, 'active') NOT IN ('released', 'available')"""
        )
        conn.commit()

    original_upgrade = m0320_migration.upgrade

    def fail_after_index_drop(cursor, use_pg):
        original_upgrade(cursor, use_pg)
        raise RuntimeError('synthetic m0320 failure after DDL')

    monkeypatch.setattr(m0320_migration, 'upgrade', fail_after_index_drop)
    with get_db_connection() as conn:
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'uq_ip_addresses_scope_active'"
        ).fetchone()[0] == 1
        assert conn.execute(
            'SELECT COUNT(*) FROM schema_migrations WHERE version = ?', (m0320_migration.VERSION,)
        ).fetchone()[0] == 0

    monkeypatch.setattr(m0320_migration, 'upgrade', original_upgrade)
    with get_db_connection() as conn:
        assert run_migrations(conn, use_pg=True, strict_history=True) == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'uq_ip_addresses_scope_active'"
        ).fetchone()[0] == 0
        assert conn.execute(
            'SELECT COUNT(*) FROM schema_migrations WHERE version = ?', (m0320_migration.VERSION,)
        ).fetchone()[0] == 1
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0


def test_conflict_scan_groups_duplicate_ip_and_mac_only_inside_one_space(isolated_db):
    del isolated_db
    first_space = _space("duplicates")
    second_space = _space("reuse")
    first_prefix = create_subnet(
        prefix="10.248.0.0/24", address_space_id=first_space["id"],
    )
    child_prefix = create_subnet(
        prefix="10.248.0.0/25", address_space_id=first_space["id"],
    )
    second_prefix = create_subnet(
        prefix="10.248.0.0/24", address_space_id=second_space["id"],
    )

    with get_db_connection() as conn:
        # Recreate inconsistent legacy facts to exercise the conflict reader.
        conn.execute("DROP INDEX IF EXISTS uq_ip_addresses_space_active")
        for row_id, prefix_id, space_id in (
            ("conflict-a-parent", first_prefix["id"], first_space["id"]),
            ("conflict-a-child", child_prefix["id"], first_space["id"]),
            ("conflict-b-other-space", second_prefix["id"], second_space["id"]),
        ):
            conn.execute(
                """INSERT INTO ip_addresses
                       (id, subnet_id, address, address_inet, address_space_id,
                        tenant_id, mac_address, status, created_at, updated_at)
                   VALUES (?, ?, '10.248.0.10', '10.248.0.10', ?,
                           'tenant-default', '00:11:22:33:44:55', 'active', 'now', 'now')""",
                (row_id, prefix_id, space_id),
            )
        conn.commit()

    result = detect_conflicts()
    assert len(result["ip_conflicts"]) == 1
    assert result["ip_conflicts"][0]["address_space_id"] == first_space["id"]
    assert result["ip_conflicts"][0]["cnt"] == 2
    assert set(result["ip_conflicts"][0]["subnets"].split(",")) == {
        first_prefix["id"], child_prefix["id"],
    }
    assert len(result["mac_conflicts"]) == 1
    assert result["mac_conflicts"][0]["address_space_id"] == first_space["id"]
    assert result["mac_conflicts"][0]["cnt"] == 2
    assert set(result["mac_conflicts"][0]["subnets"].split(",")) == {
        first_prefix["id"], child_prefix["id"],
    }
