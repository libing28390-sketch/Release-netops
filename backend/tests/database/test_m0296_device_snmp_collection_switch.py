from __future__ import annotations

from database import get_db_connection
from database.migrations.m0296_device_snmp_collection_switch import upgrade


def test_device_snmp_collection_switch_defaults_on_and_migrates_idempotently(isolated_db):
    connection = get_db_connection()
    try:
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        connection.execute("INSERT INTO devices (id) VALUES (?)", ("m0296-default-on",))
        connection.execute(
            "INSERT INTO devices (id, snmp_collection_enabled) VALUES (?, ?)",
            ("m0296-disabled", False),
        )
        connection.commit()

        rows = connection.execute(
            "SELECT id, snmp_collection_enabled FROM devices WHERE id LIKE 'm0296-%' ORDER BY id"
        ).fetchall()
        assert [(row["id"], row["snmp_collection_enabled"]) for row in rows] == [
            ("m0296-default-on", True),
            ("m0296-disabled", False),
        ]
    finally:
        connection.close()
