from services.device_health_service import _build_collection_stats, build_health_overview, evaluate_device_health, fetch_device_health_history
from database.migrations.m0060_monitoring_health_dimensions import upgrade
from services.site_identity_service import canonical_site_name, is_reserved_system_site


def test_site_display_never_falls_back_to_generated_internal_id() -> None:
    assert canonical_site_name({'site': 'site-1f5056da0738'}) == 'Unassigned'
    assert canonical_site_name({'site': 'site-1f5056da0738', 'site_name': 'WH-DC-01'}) == 'WH-DC-01'
    assert is_reserved_system_site('site-default') is True
    assert is_reserved_system_site('site-1f5056da0738') is False


def test_missing_telemetry_is_not_rendered_as_a_zero_health_score() -> None:
    result = evaluate_device_health(
        {
            "id": "d-1",
            "status": "online",
            "platform": "cisco_ios",
            "compliance": "unknown",
        }
    )

    assert result["availability_status"] == "online"
    assert result["health_status"] == "unknown"
    assert result["health_score"] is None
    assert result["health_score_available"] is False
    assert result["data_confidence"] == 0


def test_offline_availability_does_not_become_health_failure_without_evidence() -> None:
    result = evaluate_device_health(
        {
            "id": "d-2",
            "status": "offline",
            "platform": "huawei_vrp",
        }
    )

    assert result["availability_status"] == "offline"
    assert result["health_status"] == "unknown"
    assert result["health_score"] is None


def test_collected_metrics_still_drive_health_score_and_severity() -> None:
    result = evaluate_device_health(
        {
            "id": "d-3",
            "status": "online",
            "platform": "cisco_ios",
            "cpu_usage": 95,
            "memory_usage": 30,
            "temp": 35,
            "fan_status": "ok",
            "psu_status": "redundant",
        },
        collection_data={
            "collection_status": "healthy",
            "data_confidence": 100,
            "health_metrics_available": True,
        },
    )

    assert result["health_score_available"] is True
    assert result["health_status"] == "critical"
    assert result["health_score"] is not None
    assert result["health_score"] < 100


def test_overview_separates_availability_and_evaluable_health() -> None:
    overview = build_health_overview(
        [
            {
                "id": "d-1",
                "hostname": "edge-1",
                "availability_status": "online",
                "collection_status": "healthy",
                "data_confidence": 100,
                "health_status": "healthy",
                "health_score": 98,
                "health_score_available": True,
                "open_alert_count": 0,
            },
            {
                "id": "d-2",
                "hostname": "edge-2",
                "availability_status": "offline",
                "collection_status": "failed",
                "data_confidence": 0,
                "health_status": "unknown",
                "health_score": None,
                "health_score_available": False,
                "open_alert_count": 0,
            },
        ]
    )

    assert overview["total_devices"] == 2
    assert overview["online_devices"] == 1
    assert overview["offline_devices"] == 1
    assert overview["health_evaluable_count"] == 1
    assert overview["average_score"] == 98.0
    assert overview["collection_anomaly_devices"] == 1


def test_top_risky_devices_use_role_impact_within_same_health_status() -> None:
    overview = build_health_overview(
        [
            {
                "id": "access-1", "hostname": "access-1", "role": "access",
                "health_status": "critical", "health_score": 20, "health_score_available": True,
                "open_alert_count": 1, "critical_open_alerts": 1,
            },
            {
                "id": "core-1", "hostname": "core-1", "role": "core",
                "health_status": "critical", "health_score": 20, "health_score_available": True,
                "open_alert_count": 1, "critical_open_alerts": 1,
            },
        ],
        top_n=2,
    )

    assert [item["id"] for item in overview["top_risky_devices"]] == ["core-1", "access-1"]
    assert overview["top_risky_devices"][0]["impact_priority"] > overview["top_risky_devices"][1]["impact_priority"]


def test_health_dimension_migration_is_idempotent_on_sqlite_compatibility_path() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE device_health_samples (
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                status TEXT,
                health_score INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        upgrade(conn, use_pg=False)
        upgrade(conn, use_pg=False)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(device_health_samples)")}
    finally:
        conn.close()

    assert {
        "health_score_available",
        "availability_status",
        "collection_status",
        "data_confidence",
    }.issubset(columns)


def test_collection_status_marks_partial_failures_and_confidence() -> None:
    import sqlite3
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE device_collection_status (
                device_id TEXT,
                collector TEXT,
                status TEXT,
                last_success_at TEXT,
                coverage_total INTEGER,
                coverage_supported INTEGER,
                error_code TEXT,
                error_message TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO device_collection_status
                (device_id, collector, status, last_success_at, coverage_total, coverage_supported)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("d-1", "reachability", "success", now, 1, 1),
                ("d-1", "snmp_metrics", "success", now, 5, 5),
                ("d-1", "snmp_interfaces", "failed", None, 0, 0),
            ],
        )
        stats = _build_collection_stats(conn, ["d-1"])["d-1"]
    finally:
        conn.close()

    assert stats["collection_status"] == "partial_failed"
    assert stats["data_confidence"] == 67
    assert stats["health_metrics_available"] is True


def test_health_history_exposes_new_recovered_alerts_and_mttr() -> None:
    import sqlite3
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE device_health_samples (
                ts TEXT, health_score INTEGER, health_score_available INTEGER,
                health_status TEXT, availability_status TEXT, collection_status TEXT,
                data_confidence INTEGER, open_alert_count INTEGER,
                critical_open_alerts INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO device_health_samples
                (ts, health_score, health_score_available, health_status,
                 availability_status, collection_status, data_confidence,
                 open_alert_count, critical_open_alerts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ((now - timedelta(minutes=1)).isoformat(), 90, 1, "healthy", "online", "healthy", 100, 1, 0),
        )
        conn.execute("CREATE TABLE alert_events (created_at TEXT, resolved_at TEXT)")
        conn.executemany(
            "INSERT INTO alert_events (created_at, resolved_at) VALUES (?, ?)",
            [
                ((now - timedelta(minutes=10)).isoformat(), (now - timedelta(minutes=5)).isoformat()),
                ((now - timedelta(minutes=2)).isoformat(), None),
            ],
        )
        result = fetch_device_health_history(conn, range_hours=1)
    finally:
        conn.close()

    assert result["new_alerts"] == 2
    assert result["recovered_alerts"] == 1
    assert result["avg_mttr_minutes"] == 5.0
