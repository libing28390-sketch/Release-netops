from __future__ import annotations

from database import get_db_connection
from services.cmdb_snapshot_service import (
    begin_snapshot_attempt,
    complete_snapshot,
    fail_snapshot_attempt,
    replace_device_vlan_observations,
)
from services.cmdb_version_service import read_versions


def test_superseded_interface_attempt_cannot_publish_or_advance_cache_revision(isolated_db):
    old = begin_snapshot_attempt("cmdb-snapshot-device", "interface_inventory")
    current = begin_snapshot_attempt("cmdb-snapshot-device", "interface_inventory")
    conn = get_db_connection()
    try:
        assert not complete_snapshot(
            conn,
            old,
            observed_at="2026-10-27T10:00:00+00:00",
            transport="ssh",
            record_count=10,
        )
        conn.rollback()
        assert complete_snapshot(
            conn,
            current,
            observed_at="2026-10-27T10:01:00+00:00",
            transport="ssh",
            record_count=8,
            metadata={"parser": "textfsm"},
        )
        conn.commit()
        row = conn.execute(
            "SELECT attempt_generation, successful_generation, attempt_status, observed_at "
            "FROM cmdb_collection_snapshots WHERE device_id = ? AND domain = ?",
            ("cmdb-snapshot-device", "interface_inventory"),
        ).fetchone()
        assert tuple(row) == (current["generation"], current["generation"], "success", "2026-10-27T10:01:00+00:00")
        assert read_versions(conn, ["interfaces"]) == {"interfaces": 1}
    finally:
        conn.close()


def test_failed_attempt_preserves_last_success_and_vlan_observations_replace_atomically(isolated_db):
    old = begin_snapshot_attempt("cmdb-snapshot-vlan-device", "vlan_inventory")
    conn = get_db_connection()
    try:
        assert replace_device_vlan_observations(
            conn,
            {**old, "observed_at": "2026-10-27T10:00:00+00:00"},
            [{"vlan_id": 219, "site_id": "site-a", "vlan_name": "APP-219", "vlan_status": "active"}],
        ) == 1
        assert complete_snapshot(
            conn,
            old,
            observed_at="2026-10-27T10:00:00+00:00",
            transport="ssh",
            record_count=1,
        )
        conn.commit()

        newer = begin_snapshot_attempt("cmdb-snapshot-vlan-device", "vlan_inventory")
        fail_snapshot_attempt(newer, error_code="ParserMismatch")
        row = conn.execute(
            "SELECT successful_generation, attempt_status, last_success_at, failure_code "
            "FROM cmdb_collection_snapshots WHERE device_id = ? AND domain = ?",
            ("cmdb-snapshot-vlan-device", "vlan_inventory"),
        ).fetchone()
        observations = conn.execute(
            "SELECT vlan_id, vlan_name, generation, observed_at FROM cmdb_device_vlan_observations WHERE device_id = ?",
            ("cmdb-snapshot-vlan-device",),
        ).fetchall()
        assert row["successful_generation"] == old["generation"]
        assert row["attempt_status"] == "failed"
        assert row["last_success_at"] == "2026-10-27T10:00:00+00:00"
        assert row["failure_code"] == "ParserMismatch"
        assert [tuple(item) for item in observations] == [
            (219, "APP-219", old["generation"], "2026-10-27T10:00:00+00:00")
        ]
    finally:
        conn.close()


def test_vlan_snapshot_replacement_removes_only_prior_device_generation(isolated_db):
    first = begin_snapshot_attempt("cmdb-vlan-replace-device", "vlan_inventory")
    conn = get_db_connection()
    try:
        replace_device_vlan_observations(
            conn,
            {**first, "observed_at": "2026-10-27T10:00:00+00:00"},
            [
                {"vlan_id": 219, "site_id": "site-a", "vlan_name": "APP-219"},
                {"vlan_id": 220, "site_id": "site-a", "vlan_name": "APP-220"},
            ],
        )
        assert complete_snapshot(
            conn, first, observed_at="2026-10-27T10:00:00+00:00", transport="ssh", record_count=2,
        )
        conn.commit()

        second = begin_snapshot_attempt("cmdb-vlan-replace-device", "vlan_inventory")
        replace_device_vlan_observations(
            conn,
            {**second, "observed_at": "2026-10-27T11:00:00+00:00"},
            [{"vlan_id": 219, "site_id": "site-a", "vlan_name": "APP-219-UPDATED"}],
        )
        assert complete_snapshot(
            conn, second, observed_at="2026-10-27T11:00:00+00:00", transport="ssh", record_count=1,
        )
        conn.commit()
        rows = conn.execute(
            "SELECT vlan_id, vlan_name, generation FROM cmdb_device_vlan_observations "
            "WHERE device_id = ? ORDER BY vlan_id",
            ("cmdb-vlan-replace-device",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (219, "APP-219-UPDATED", second["generation"]),
        ]
    finally:
        conn.close()
