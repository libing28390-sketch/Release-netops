import pytest
from database import get_db_connection

def test_supporting_engine_tables_exist(isolated_db):
    conn = get_db_connection()
    try:
        for table in ["config_backups", "alarms", "performance_metrics", "events", "discovery_jobs"]:
            cursor = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            assert cursor.fetchone() is not None, f"Table {table} must exist"
    finally:
        conn.close()

def test_config_snapshots_trigger_sync(isolated_db):
    conn = get_db_connection()
    try:
        # Clear tables
        conn.execute("DELETE FROM config_backups")
        conn.execute("DELETE FROM config_snapshots")
        conn.execute("DELETE FROM devices")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status) VALUES ('dev-1', 'switch-1', '10.0.0.1', 'online')")
        conn.commit()

        # Insert a snapshot
        conn.execute(
            '''
            INSERT INTO config_snapshots (id, device_id, hostname, vendor, timestamp, trigger, author, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            ("snap-123", "dev-1", "switch-1", "cisco_ios", "2026-06-13T12:00:00", "manual", "admin", "/path/to/file")
        )
        conn.commit()

        # Verify backup was automatically created in config_backups by trigger
        cursor = conn.execute("SELECT * FROM config_backups WHERE id = 'snap-123'")
        row = cursor.fetchone()
        assert row is not None
        assert row['device_id'] == "dev-1"
        assert row['config_type'] == "running"
        assert row['backup_time'] == "2026-06-13T12:00:00"
        assert row['file_path'] == "/path/to/file"

        # Update snapshot tag
        conn.execute("UPDATE config_snapshots SET tag = 'baseline' WHERE id = 'snap-123'")
        conn.commit()

        cursor = conn.execute("SELECT config_hash FROM config_backups WHERE id = 'snap-123'")
        assert cursor.fetchone()['config_hash'] == "baseline"

        # Delete snapshot
        conn.execute("DELETE FROM config_snapshots WHERE id = 'snap-123'")
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) AS c FROM config_backups WHERE id = 'snap-123'")
        assert cursor.fetchone()['c'] == 0

    finally:
        conn.close()

def test_alert_events_trigger_sync(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM alarms")
        conn.execute("DELETE FROM alert_events")
        conn.commit()

        # Insert alert event
        conn.execute(
            '''
            INSERT INTO alert_events (id, dedupe_key, source, severity, title, message, device_id, created_at, workflow_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            ("alert-1", "key-1", "ping", "critical", "Ping Failed", "Ping packet loss", "dev-1", "2026-06-13T12:00:00", "open")
        )
        conn.commit()

        # Verify alarm was automatically created
        cursor = conn.execute("SELECT * FROM alarms WHERE id = 'alert-1'")
        row = cursor.fetchone()
        assert row is not None
        assert row['device_id'] == "dev-1"
        assert row['severity'] == "critical"
        assert row['alarm_type'] == "Ping Failed"
        assert row['status'] == "open"

    finally:
        conn.close()

def test_telemetry_to_perf_metrics_trigger(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM performance_metrics")
        conn.execute("DELETE FROM device_telemetry_samples")
        conn.commit()

        # Insert telemetry sample
        conn.execute(
            '''
            INSERT INTO device_telemetry_samples (ts, device_id, cpu_util, mem_avail, cpu_load, disk_util)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            ("2026-06-13T12:00:00", "dev-1", 45.5, 8192.0, 1.5, 30.0)
        )
        conn.commit()

        # Verify performance metrics were created
        cursor = conn.execute("SELECT * FROM performance_metrics WHERE device_id = 'dev-1' AND metric_name = 'cpu_util'")
        row = cursor.fetchone()
        assert row is not None
        assert row['metric_value'] == 45.5
        assert row['timestamp'] == "2026-06-13T12:00:00"

        cursor = conn.execute("SELECT * FROM performance_metrics WHERE device_id = 'dev-1' AND metric_name = 'mem_avail'")
        row = cursor.fetchone()
        assert row is not None
        assert row['metric_value'] == 8192.0

    finally:
        conn.close()
