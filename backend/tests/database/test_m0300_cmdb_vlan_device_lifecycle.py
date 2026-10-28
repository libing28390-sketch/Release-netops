from __future__ import annotations

from database import get_db_connection
from database.migrations.m0300_cmdb_vlan_device_lifecycle import upgrade


def _drop_device_fk(conn, table_name: str) -> None:
    conn.execute(f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{table_name}_device_id_fkey"')


def _device_delete_rule(conn, table_name: str) -> str:
    row = conn.execute(
        """SELECT c.confdeltype
           FROM pg_constraint c
           JOIN pg_class local_table ON local_table.oid = c.conrelid
           JOIN pg_namespace n ON n.oid = local_table.relnamespace
           WHERE n.nspname = current_schema()
             AND local_table.relname = ?
             AND c.contype = 'f'
             AND pg_get_constraintdef(c.oid) LIKE 'FOREIGN KEY (device_id) REFERENCES devices(id)%'
             AND pg_get_constraintdef(c.oid) LIKE '%ON DELETE CASCADE%'""",
        (table_name,),
    ).fetchone()
    return str(row[0]) if row else ""


def test_m0300_repairs_orphans_and_cascades_device_owned_vlan_facts(isolated_db):
    conn = get_db_connection()
    try:
        tracked = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 300"
        ).fetchone()
        assert tracked["name"] == "cmdb_vlan_device_lifecycle"

        conn.execute("SAVEPOINT m0300_upgrade_test")
        _drop_device_fk(conn, "cmdb_collection_snapshots")
        _drop_device_fk(conn, "cmdb_device_vlan_observations")
        conn.execute(
            "INSERT INTO devices (id, hostname, status) VALUES (?, ?, ?)",
            ("m0300-valid-device", "m0300-valid-device", "online"),
        )
        conn.execute(
            "INSERT INTO cmdb_collection_snapshots (device_id, domain) VALUES (?, ?)",
            ("m0300-valid-device", "vlan_inventory"),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations
               (device_id, vlan_id, generation) VALUES (?, ?, ?)""",
            ("m0300-valid-device", 340, 1),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_port_observations
               (device_id, vlan_id, normalized_interface_name, interface_name,
                generation, observed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("m0300-valid-device", 340, "gi0/0/1", "GE0/0/1", 1, "2026-10-28T01:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO cmdb_collection_snapshots (device_id, domain) VALUES (?, ?)",
            ("m0300-orphan-device", "interface_inventory"),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations
               (device_id, vlan_id, generation) VALUES (?, ?, ?)""",
            ("m0300-orphan-device", 341, 1),
        )
        conn.execute(
            """INSERT INTO cmdb_device_vlan_port_observations
               (device_id, vlan_id, normalized_interface_name, interface_name,
                generation, observed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("m0300-orphan-device", 341, "gi0/0/2", "GE0/0/2", 1, "2026-10-28T01:00:00+00:00"),
        )

        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)

        assert _device_delete_rule(conn, "cmdb_collection_snapshots") == "c"
        assert _device_delete_rule(conn, "cmdb_device_vlan_observations") == "c"
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_collection_snapshots WHERE device_id = ?",
            ("m0300-orphan-device",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_observations WHERE device_id = ?",
            ("m0300-orphan-device",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_port_observations WHERE device_id = ?",
            ("m0300-orphan-device",),
        ).fetchone()[0] == 0

        conn.execute("DELETE FROM devices WHERE id = ?", ("m0300-valid-device",))
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_collection_snapshots WHERE device_id = ?",
            ("m0300-valid-device",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_observations WHERE device_id = ?",
            ("m0300-valid-device",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_vlan_port_observations WHERE device_id = ?",
            ("m0300-valid-device",),
        ).fetchone()[0] == 0

        conn.execute("ROLLBACK TO SAVEPOINT m0300_upgrade_test")
        conn.execute("RELEASE SAVEPOINT m0300_upgrade_test")
        conn.commit()
    finally:
        conn.close()
