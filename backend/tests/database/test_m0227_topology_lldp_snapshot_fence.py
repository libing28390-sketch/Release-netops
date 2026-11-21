from __future__ import annotations

import uuid

import pytest
from psycopg2.errors import CheckViolation, ForeignKeyViolation, NotNullViolation

from database import get_db_connection
from database.migrations import m0227_topology_lldp_snapshot_fence as migration


def _device_id(conn, label: str) -> str:
    device_id = f"lldp-snapshot-{label}-{uuid.uuid4().hex}"
    conn.execute(
        "INSERT INTO devices (id, hostname) VALUES (?, ?)",
        (device_id, device_id),
    )
    return device_id


def test_m0227_creates_postgresql_table_idempotently_with_contract(isolated_db) -> None:
    conn = get_db_connection()
    try:
        # Bootstrap has already applied the migration. Reconstruct its previous
        # shape in this disposable database and exercise the upgrade twice.
        conn.execute("DROP TABLE IF EXISTS topology_device_lldp_snapshots")
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        columns = {
            str(row[0]): (str(row[1]), str(row[2]), row[3])
            for row in conn.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'topology_device_lldp_snapshots'"""
            ).fetchall()
        }
        assert columns == {
            "device_id": ("text", "NO", None),
            "generation": ("bigint", "NO", "0"),
            "state": ("text", "NO", "'unknown'::text"),
            "snapshot_complete": ("boolean", "NO", "false"),
            "observation_count": ("integer", "NO", "0"),
            "started_at": ("timestamp with time zone", "YES", None),
            "completed_at": ("timestamp with time zone", "YES", None),
            "action_version": ("text", "NO", "''::text"),
            "parser_version": ("text", "NO", "''::text"),
            "schema_version": ("text", "NO", "''::text"),
            "updated_at": ("timestamp with time zone", "NO", None),
        }

        constraints = {
            (str(row[0]), str(row[1]), str(row[2]))
            for row in conn.execute(
                """SELECT c.contype, c.confdeltype, pg_get_constraintdef(c.oid)
                     FROM pg_constraint c
                     JOIN pg_class t ON t.oid = c.conrelid
                     JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = current_schema()
                      AND t.relname = 'topology_device_lldp_snapshots'"""
            ).fetchall()
        }
        assert any(
            kind == "p" and "PRIMARY KEY (device_id)" in definition
            for kind, _, definition in constraints
        )
        assert any(
            kind == "f"
            and delete_action == "c"
            and "FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE" in definition
            for kind, delete_action, definition in constraints
        )
        assert any("generation >= 0" in definition for _, _, definition in constraints)
        assert any("observation_count >= 0" in definition for _, _, definition in constraints)
        assert any(
            "state = ANY" in definition
            and all(state in definition for state in ("unknown", "collecting", "complete", "failed"))
            for _, _, definition in constraints
        )

        device_id = _device_id(conn, "defaults")
        conn.execute(
            "INSERT INTO topology_device_lldp_snapshots (device_id, updated_at) "
            "VALUES (?, clock_timestamp())",
            (device_id,),
        )
        defaults = conn.execute(
            """SELECT generation, state, snapshot_complete, observation_count,
                      started_at, completed_at, action_version, parser_version,
                      schema_version, updated_at
                 FROM topology_device_lldp_snapshots WHERE device_id = ?""",
            (device_id,),
        ).fetchone()
        assert tuple(defaults[:9]) == (0, "unknown", False, 0, None, None, "", "", "")
        assert defaults[9] is not None

        migration.downgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert conn.execute(
            "SELECT generation FROM topology_device_lldp_snapshots WHERE device_id = ?",
            (device_id,),
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_m0227_constraints_reject_invalid_values_and_missing_devices(isolated_db) -> None:
    conn = get_db_connection()
    try:
        device_id = _device_id(conn, "constraints")
        conn.execute(
            "INSERT INTO topology_device_lldp_snapshots (device_id, updated_at) "
            "VALUES (?, clock_timestamp())",
            (device_id,),
        )
        conn.commit()

        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE topology_device_lldp_snapshots SET generation = -1 WHERE device_id = ?",
                (device_id,),
            )
        conn.rollback()

        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE topology_device_lldp_snapshots SET observation_count = -1 WHERE device_id = ?",
                (device_id,),
            )
        conn.rollback()

        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE topology_device_lldp_snapshots SET state = 'partial' WHERE device_id = ?",
                (device_id,),
            )
        conn.rollback()

        with pytest.raises(ForeignKeyViolation):
            conn.execute(
                "INSERT INTO topology_device_lldp_snapshots (device_id, updated_at) "
                "VALUES (?, clock_timestamp())",
                (f"missing-{uuid.uuid4().hex}",),
            )
        conn.rollback()

        with pytest.raises(NotNullViolation):
            conn.execute(
                "INSERT INTO topology_device_lldp_snapshots (device_id) VALUES (?)",
                (device_id,),
            )
        conn.rollback()

        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
        assert conn.execute(
            "SELECT 1 FROM topology_device_lldp_snapshots WHERE device_id = ?",
            (device_id,),
        ).fetchone() is None
    finally:
        conn.close()
