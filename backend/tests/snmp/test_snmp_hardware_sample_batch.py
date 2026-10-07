from __future__ import annotations

from datetime import datetime, timedelta, timezone

import database
from services.snmp_hardware_inventory_service import record_sensor_samples_batch


def _seed_device(conn, device_id: str) -> None:
    conn.execute(
        """
        INSERT INTO devices (id, hostname, tenant_id, asset_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        (device_id, "batch-edge", "tenant-default", "asset-batch-edge"),
    )


def _seed_sensor(
    conn,
    *,
    device_id: str,
    sensor_key: str,
    last_seen: datetime,
    updated_at: datetime | None = None,
    last_success: datetime | None = None,
    lifecycle_status: str = "active",
    discovery_status: str = "present",
    missing_success_count: int = 0,
    last_missing_run_id: str = "",
    enabled: bool = True,
    last_value: float | None = None,
    last_raw_value: str | None = None,
    last_quality: str = "missing",
) -> None:
    conn.execute(
        """
        INSERT INTO snmp_hardware_sensors (
            sensor_id, device_id, sensor_key, source_type, source_id,
            component_class, measurement_type, index_json, first_seen, last_seen, updated_at,
            last_success, last_sample_at, lifecycle_status, discovery_status, missing_success_count,
            last_missing_run_id, enabled, last_value, last_raw_value, last_quality
        )
        VALUES (?, ?, ?, 'entity_sensor', '', 'temperature', 'temperature_celsius', jsonb_build_array(?),
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"batch-id-{sensor_key}",
            device_id,
            sensor_key,
            sensor_key,
            last_seen,
            last_seen,
            updated_at or last_seen,
            last_success,
            last_success,
            lifecycle_status,
            discovery_status,
            missing_success_count,
            last_missing_run_id,
            enabled,
            last_value,
            last_raw_value,
            last_quality,
        ),
    )


def _sensor(conn, device_id: str, sensor_key: str):
    return conn.execute(
        """
        SELECT last_value, last_raw_value, last_quality, last_seen, last_success,
               last_sample_at, updated_at, lifecycle_status, discovery_status, missing_success_count,
               last_missing_run_id, enabled
          FROM snmp_hardware_sensors
         WHERE device_id = ? AND sensor_key = ?
        """,
        (device_id, sensor_key),
    ).fetchone()


def test_batch_updates_values_with_shared_single_sample_normalization(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-batch-normalize-device"
        t0 = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
        _seed_device(conn, device_id)
        _seed_sensor(conn, device_id=device_id, sensor_key="normalized", last_seen=t0)
        _seed_sensor(conn, device_id=device_id, sensor_key="missing", last_seen=t0)
        conn.commit()

        updated = record_sensor_samples_batch(
            conn,
            [
                {
                    "device_id": f" {device_id} ",
                    "sensor_key": " normalized ",
                    "value": "12.5",
                    "raw_value": " raw\x00value ",
                    "quality": " GOOD ",
                    "observed_at": "2026-10-07T09:03:00+09:00",
                },
                {
                    "device_id": device_id,
                    "sensor_key": "missing",
                    "value": None,
                    "raw_value": None,
                    "quality": "missing",
                    "observed_at": t0 + timedelta(minutes=4),
                },
            ],
        )
        conn.commit()

        assert updated == 2
        good = _sensor(conn, device_id, "normalized")
        assert good["last_value"] == 12.5
        assert good["last_raw_value"] == "rawvalue"
        assert good["last_quality"] == "good"
        assert good["last_seen"] == datetime(2026, 10, 7, 0, 3, tzinfo=timezone.utc)
        assert good["last_success"] == good["last_seen"]
        assert good["discovery_status"] == "present"

        missing = _sensor(conn, device_id, "missing")
        assert missing["last_value"] is None
        assert missing["last_raw_value"] is None
        assert missing["last_quality"] == "missing"
        assert missing["last_seen"] == t0 + timedelta(minutes=4)
        assert missing["last_success"] is None
    finally:
        conn.close()


def test_batch_skips_stale_samples_and_missing_targets(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-batch-stale-device"
        t0 = datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)
        _seed_device(conn, device_id)
        _seed_sensor(
            conn,
            device_id=device_id,
            sensor_key="existing",
            last_seen=t0 + timedelta(minutes=10),
            updated_at=t0 + timedelta(minutes=10),
            last_success=t0 + timedelta(minutes=8),
            last_value=22,
            last_raw_value="22",
            last_quality="good",
        )
        conn.commit()

        updated = record_sensor_samples_batch(
            conn,
            [
                {
                    "device_id": device_id,
                    "sensor_key": "existing",
                    "value": 5,
                    "raw_value": "5",
                    "quality": "good",
                    "observed_at": t0 + timedelta(minutes=5),
                },
                {
                    "device_id": device_id,
                    "sensor_key": "not-discovered",
                    "value": 99,
                    "raw_value": "99",
                    "quality": "good",
                    "observed_at": t0 + timedelta(minutes=20),
                },
            ],
        )
        conn.commit()

        assert updated == 0
        existing = _sensor(conn, device_id, "existing")
        assert existing["last_value"] == 22
        assert existing["last_raw_value"] == "22"
        assert existing["last_seen"] == t0 + timedelta(minutes=10)
        assert existing["last_success"] == t0 + timedelta(minutes=8)
        assert existing["last_sample_at"] == t0 + timedelta(minutes=8)
        absent_count = conn.execute(
            "SELECT COUNT(*) FROM snmp_hardware_sensors WHERE device_id = ? AND sensor_key = ?",
            (device_id, "not-discovered"),
        ).fetchone()[0]
        assert absent_count == 0
    finally:
        conn.close()


def test_batch_accepts_a_chunk_containing_only_null_numeric_values(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-batch-all-null-device"
        observed_at = datetime(2026, 10, 7, 1, 30, tzinfo=timezone.utc)
        _seed_device(conn, device_id)
        _seed_sensor(conn, device_id=device_id, sensor_key="missing-a", last_seen=observed_at)
        _seed_sensor(conn, device_id=device_id, sensor_key="missing-b", last_seen=observed_at)
        conn.commit()

        updated = record_sensor_samples_batch(
            conn,
            [
                {
                    "device_id": device_id,
                    "sensor_key": "missing-a",
                    "value": None,
                    "raw_value": None,
                    "quality": "missing",
                    "observed_at": observed_at + timedelta(seconds=1),
                },
                {
                    "device_id": device_id,
                    "sensor_key": "missing-b",
                    "value": None,
                    "raw_value": "unreadable text",
                    "quality": "invalid",
                    "observed_at": observed_at + timedelta(seconds=2),
                },
            ],
        )
        conn.commit()

        assert updated == 2
        missing = _sensor(conn, device_id, "missing-a")
        assert missing["last_value"] is None
        assert missing["last_raw_value"] is None
        assert missing["last_quality"] == "missing"
        invalid = _sensor(conn, device_id, "missing-b")
        assert invalid["last_value"] is None
        assert invalid["last_raw_value"] == "unreadable text"
        assert invalid["last_quality"] == "invalid"
    finally:
        conn.close()


def test_batch_preserves_good_component_presence_and_bad_quality_lifecycle(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-batch-state-device"
        t0 = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)
        _seed_device(conn, device_id)
        _seed_sensor(
            conn,
            device_id=device_id,
            sensor_key="component",
            last_seen=t0,
            last_success=t0,
            lifecycle_status="retired",
            discovery_status="present",
            missing_success_count=4,
            last_missing_run_id="missing-run",
            enabled=False,
        )
        _seed_sensor(
            conn,
            device_id=device_id,
            sensor_key="bad-quality",
            last_seen=t0,
            last_success=t0,
            lifecycle_status="retired",
            discovery_status="not_present",
            missing_success_count=7,
            last_missing_run_id="bad-run",
            enabled=False,
        )
        conn.commit()

        updated = record_sensor_samples_batch(
            conn,
            [
                {
                    "device_id": device_id,
                    "sensor_key": "component",
                    "value": 0,
                    "raw_value": "0",
                    "quality": "good",
                    "observed_at": t0 + timedelta(minutes=1),
                    "presence_status": "NOT_PRESENT",
                },
                {
                    "device_id": device_id,
                    "sensor_key": "bad-quality",
                    "value": None,
                    "raw_value": "unreadable",
                    "quality": "invalid",
                    "observed_at": t0 + timedelta(minutes=2),
                    "presence_status": "present",
                },
            ],
        )
        conn.commit()

        assert updated == 2
        component = _sensor(conn, device_id, "component")
        assert component["discovery_status"] == "not_present"
        assert component["lifecycle_status"] == "active"
        assert component["enabled"] is True
        assert component["missing_success_count"] == 0
        assert component["last_missing_run_id"] == ""
        assert component["last_success"] == t0 + timedelta(minutes=1)

        bad = _sensor(conn, device_id, "bad-quality")
        assert bad["last_value"] is None
        assert bad["last_raw_value"] == "unreadable"
        assert bad["last_quality"] == "invalid"
        assert bad["last_seen"] == t0 + timedelta(minutes=2)
        assert bad["updated_at"] == t0 + timedelta(minutes=2)
        assert bad["last_success"] == t0
        assert bad["lifecycle_status"] == "retired"
        assert bad["discovery_status"] == "not_present"
        assert bad["enabled"] is False
        assert bad["missing_success_count"] == 7
        assert bad["last_missing_run_id"] == "bad-run"
    finally:
        conn.close()


class _CountingConnection:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.batch_parameter_counts: list[int] = []

    def execute(self, statement, params=None):
        if "UPDATE snmp_hardware_sensors AS sensor" in str(statement):
            self.batch_parameter_counts.append(len(params or ()))
        return self.connection.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_batch_bounds_multirow_updates_and_parameters_across_chunks(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-batch-chunks-device"
        t0 = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)
        sensor_count = 1001
        _seed_device(conn, device_id)
        conn.execute(
            """
            INSERT INTO snmp_hardware_sensors (
                sensor_id, device_id, sensor_key, source_type, source_id,
                component_class, measurement_type, index_json, first_seen, last_seen, updated_at
            )
            SELECT 'batch-chunk-id-' || sensor_number::text,
                   ?, 'chunk-' || sensor_number::text, 'entity_sensor', '',
                   'temperature', 'temperature_celsius', jsonb_build_array(sensor_number), ?, ?, ?
              FROM generate_series(1, ?) AS sensors(sensor_number)
            """,
            (device_id, t0, t0, t0, sensor_count),
        )
        conn.commit()

        samples = (
            {
                "device_id": device_id,
                "sensor_key": f"chunk-{sensor_number}",
                "value": sensor_number,
                "raw_value": str(sensor_number),
                "quality": "good",
                "observed_at": t0 + timedelta(minutes=1),
            }
            for sensor_number in range(1, sensor_count + 1)
        )
        counting_conn = _CountingConnection(conn)
        updated = record_sensor_samples_batch(counting_conn, samples)
        conn.commit()

        assert updated == sensor_count
        assert len(counting_conn.batch_parameter_counts) == 3
        assert counting_conn.batch_parameter_counts == [3500, 3500, 7]
        assert max(counting_conn.batch_parameter_counts) <= 3500
    finally:
        conn.close()
