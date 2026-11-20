from __future__ import annotations

import pytest

from database import get_db_connection
from database.migrations import m0262_interface_packet_counter_numeric as migration


RAW_COLUMNS = (
    "in_pkts",
    "out_pkts",
    "in_errors",
    "out_errors",
    "in_discards",
    "out_discards",
    "fcs_errors",
    "frame_too_long_errors",
    "mac_rx_errors",
    "symbol_errors",
)
ROLLUP_COLUMNS = (
    "in_pkts_sum",
    "out_pkts_sum",
    "err_delta_sum",
    "discard_delta_sum",
    "fcs_sum",
)
UINT64_MAX = 18_446_744_073_709_551_615
THREE_UINT64_MAX = UINT64_MAX * 3


def _types(connection, table: str) -> dict[str, tuple[str, int | None, int | None]]:
    return {
        row[0]: (row[1], row[2], row[3])
        for row in connection.execute(
            """
            SELECT column_name, data_type, numeric_precision, numeric_scale
              FROM information_schema.columns
             WHERE table_schema = current_schema() AND table_name = ?
            """,
            (table,),
        ).fetchall()
    }


def _make_legacy_integer_schema(connection) -> None:
    for table, columns in (
        ("interface_telemetry_raw", RAW_COLUMNS),
        ("interface_telemetry_1m", ROLLUP_COLUMNS),
    ):
        for column in columns:
            if table == "interface_telemetry_1m":
                connection.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"
                )
            connection.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE INTEGER "
                f"USING {column}::integer"
            )
            if table == "interface_telemetry_1m":
                connection.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT 0"
                )


def test_m0262_fresh_schema_has_lossless_counter_types(isolated_db):
    connection = get_db_connection()
    try:
        raw = _types(connection, "interface_telemetry_raw")
        rollup = _types(connection, "interface_telemetry_1m")
        assert raw["in_pkts"] == ("numeric", 20, 0)
        assert raw["out_pkts"] == ("numeric", 20, 0)
        assert raw["in_errors"][0] == "bigint"
        assert raw["out_discards"][0] == "bigint"
        for column in ("fcs_errors", "frame_too_long_errors", "mac_rx_errors", "symbol_errors"):
            assert raw[column] == ("numeric", 20, 0)
        for column in ROLLUP_COLUMNS:
            assert rollup[column] == ("numeric", None, None)
    finally:
        connection.close()


def test_m0262_upgrades_legacy_integer_schema_preserves_values_and_is_idempotent(isolated_db):
    connection = get_db_connection()
    try:
        _make_legacy_integer_schema(connection)
        connection.execute(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, in_pkts, out_pkts, in_errors,
                 out_errors, in_discards, out_discards, fcs_errors,
                 frame_too_long_errors, mac_rx_errors, symbol_errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-02T15:00:00Z", "device-1", "ge-0/0/1", 123, 124, 125,
             126, 127, 128, 129, 130, 131, 132),
        )
        connection.execute(
            """
            INSERT INTO interface_telemetry_1m
                (ts_minute, device_id, interface_name, in_pkts_sum,
                 out_pkts_sum, err_delta_sum, discard_delta_sum, fcs_sum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-02T15:00:00Z", "device-1", "ge-0/0/1", 223, 224, 225, 226, 227),
        )
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        raw = _types(connection, "interface_telemetry_raw")
        rollup = _types(connection, "interface_telemetry_1m")
        assert raw["in_pkts"] == ("numeric", 20, 0)
        assert raw["in_errors"][0] == "bigint"
        assert rollup["in_pkts_sum"] == ("numeric", None, None)
        assert rollup["err_delta_sum"] == ("numeric", None, None)
        assert tuple(connection.execute(
            "SELECT in_pkts, out_pkts, fcs_errors FROM interface_telemetry_raw"
        ).fetchone()) == (123, 124, 129)
        assert tuple(connection.execute(
            "SELECT in_pkts_sum, err_delta_sum, fcs_sum FROM interface_telemetry_1m"
        ).fetchone()) == (223, 225, 227)

        connection.execute(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, in_pkts, out_pkts)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-10-02T15:00:10Z", "device-4", "ge-0/0/4", THREE_UINT64_MAX, THREE_UINT64_MAX),
        )
        connection.execute(
            """
            INSERT INTO interface_telemetry_1m
                (ts_minute, device_id, interface_name, in_pkts_sum, out_pkts_sum)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-10-02T15:00:00Z", "device-4", "ge-0/0/4", THREE_UINT64_MAX, THREE_UINT64_MAX),
        )
        connection.commit()
        assert int(connection.execute(
            "SELECT in_pkts FROM interface_telemetry_raw WHERE device_id = ?",
            ("device-4",),
        ).fetchone()[0]) == THREE_UINT64_MAX

        for index in range(3):
            connection.execute(
                """
                INSERT INTO interface_telemetry_raw
                    (ts, device_id, interface_name, in_pkts, out_pkts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"2026-10-02T15:00:0{index}Z", "device-2", "ge-0/0/2", UINT64_MAX, UINT64_MAX),
            )
        connection.commit()
        row = connection.execute(
            """
            SELECT SUM(in_pkts), SUM(out_pkts)
              FROM interface_telemetry_raw
             WHERE device_id = ?
            """,
            ("device-2",),
        ).fetchone()
        assert tuple(int(value) for value in row) == (THREE_UINT64_MAX, THREE_UINT64_MAX)
    finally:
        connection.close()


def test_m0262_downgrade_rejects_lossy_values_without_clamping(isolated_db):
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, in_pkts)
            VALUES (?, ?, ?, ?)
            """,
            ("2026-10-02T15:00:00Z", "device-3", "ge-0/0/3", THREE_UINT64_MAX),
        )
        connection.commit()
        with pytest.raises(ValueError, match="outside"):
            migration.downgrade(connection.cursor(), use_pg=True)
        connection.rollback()
        assert _types(connection, "interface_telemetry_raw")["in_pkts"] == ("numeric", 20, 0)
        assert int(connection.execute(
            "SELECT in_pkts FROM interface_telemetry_raw WHERE device_id = ?",
            ("device-3",),
        ).fetchone()[0]) == THREE_UINT64_MAX
    finally:
        connection.close()
