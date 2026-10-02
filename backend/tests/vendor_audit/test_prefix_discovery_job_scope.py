from __future__ import annotations

import json

from services import prefix_discovery_service as prefix_service
from services import read_only_collection_adapter as read_only_adapter


def _insert_device(database, device_id: str, *, policy: dict | None = None, status: str = "online") -> None:
    conn = database.get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO devices (
                id, hostname, status, role, platform, tenant_id, collection_policy_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                device_id,
                status,
                "router",
                "cisco_ios",
                "tenant-default",
                json.dumps(policy or {}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_prefix(
    database,
    prefix_id: str,
    *,
    discovered_devices: list[str] | None,
    network_octet: int,
    source_type: str = "discovery",
    manual_override: int = 0,
    last_seen_at: str = "2026-01-01T00:00:00+00:00",
    miss_count: int = 0,
) -> None:
    conn = database.get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO prefixes (
                id, prefix, prefix_cidr, tenant_id, status, source_type,
                manual_override, discovered_devices_json, last_seen_at,
                miss_count, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prefix_id,
                f"198.51.100.{network_octet}/32",
                f"198.51.100.{network_octet}/32",
                "tenant-default",
                "active",
                source_type,
                manual_override,
                json.dumps(discovered_devices if discovered_devices is not None else []),
                last_seen_at,
                miss_count,
                1,
                last_seen_at,
                last_seen_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_observation(
    database,
    prefix_id: str,
    observation_id: str,
    *,
    source_device_id: str,
    collection_run_id: str = "old-run",
) -> None:
    conn = database.get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO prefix_observations (
                id, prefix_id, collection_run_id, source_device_id,
                source_type, observed_value, first_seen_at, last_seen_at,
                miss_count, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                prefix_id,
                collection_run_id,
                source_device_id,
                "interface",
                prefix_id,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                0,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_empty_read_only_evidence_envelope_is_partial(monkeypatch) -> None:
    monkeypatch.setattr(
        read_only_adapter,
        "collect_operational_data",
        lambda *_args, **_kwargs: {"categories": []},
    )

    result = read_only_adapter.collect_read_only_evidence({"id": "device-empty"})

    assert result["status"] == "partial"
    assert result["summary"]["total_categories"] == 0


def test_job_does_not_age_prefix_when_real_discovery_gets_empty_categories(
    isolated_db, monkeypatch
) -> None:
    database = isolated_db["module"]
    _insert_device(database, "device-empty")
    _insert_prefix(
        database,
        "prefix-empty-evidence",
        discovered_devices=["device-empty"],
        network_octet=18,
        miss_count=2,
    )
    _insert_observation(
        database,
        "prefix-empty-evidence",
        "observation-empty-evidence",
        source_device_id="device-empty",
    )

    monkeypatch.setattr(
        read_only_adapter,
        "collect_operational_data",
        lambda *_args, **_kwargs: {"categories": []},
    )

    result = prefix_service.run_prefix_discovery_job()

    assert result["successful_devices"] == 0
    assert result["partial_devices"] == 1
    assert result["failed_devices"] == 0
    assert result["aged_prefixes"] == 0

    conn = database.get_db_connection()
    try:
        row = conn.execute(
            "SELECT miss_count, is_active, status FROM prefixes WHERE id = ?",
            ("prefix-empty-evidence",),
        ).fetchone()
    finally:
        conn.close()
    assert dict(row) == {"miss_count": 2, "is_active": 1, "status": "active"}


def test_job_honors_prefix_projection_and_only_complete_success_covers_aging(
    isolated_db, monkeypatch
) -> None:
    database = isolated_db["module"]
    _insert_device(
        database,
        "device-disabled",
        policy={"collectors": {"prefix_projection": False}},
    )
    _insert_device(database, "device-success")
    _insert_device(database, "device-partial")
    _insert_device(database, "device-unknown")
    _insert_device(database, "device-error")

    discovered: list[str] = []
    statuses = {
        "device-success": "success",
        "device-partial": "partial",
        "device-unknown": "unknown",
    }

    def fake_discover(device, **_kwargs):
        device_id = str(device["id"])
        discovered.append(device_id)
        if device_id == "device-error":
            raise RuntimeError("mock collection failure")
        return {"created": 1, "updated": 2, "collection_status": statuses[device_id]}

    age_calls: list[dict] = []

    def fake_age(**kwargs):
        age_calls.append(kwargs)
        return 0

    monkeypatch.setattr(prefix_service, "discover_prefixes_for_device", fake_discover)
    monkeypatch.setattr(prefix_service, "age_missing_prefixes", fake_age)

    result = prefix_service.run_prefix_discovery_job()

    assert "device-disabled" not in discovered
    assert result["devices"] == 5
    assert result["successful_devices"] == 1
    assert result["partial_devices"] == 1
    assert result["failed_devices"] == 2
    assert result["skipped_devices"] == 1
    assert result["created"] == 3
    assert result["updated"] == 6
    assert age_calls[0]["covered_device_ids"] == {"device-success"}


def test_age_missing_prefixes_requires_complete_owner_coverage_and_protects_manual_and_current_run(
    isolated_db,
) -> None:
    database = isolated_db["module"]
    _insert_prefix(database, "prefix-success", discovered_devices=["device-online"], network_octet=11)
    _insert_observation(database, "prefix-success", "observation-success", source_device_id="device-online")

    _insert_prefix(database, "prefix-offline", discovered_devices=["device-offline"], network_octet=12)
    _insert_observation(database, "prefix-offline", "observation-offline", source_device_id="device-offline")

    _insert_prefix(database, "prefix-shared", discovered_devices=["device-online", "device-offline"], network_octet=13)
    _insert_observation(database, "prefix-shared", "observation-shared-online", source_device_id="device-online")
    _insert_observation(database, "prefix-shared", "observation-shared-offline", source_device_id="device-offline")

    _insert_prefix(database, "prefix-unknown", discovered_devices=["device-online"], network_octet=14)
    _insert_observation(database, "prefix-unknown", "observation-unknown", source_device_id="")

    _insert_prefix(
        database,
        "prefix-manual",
        discovered_devices=["device-online"],
        network_octet=15,
        source_type="manual",
        manual_override=1,
    )
    _insert_observation(database, "prefix-manual", "observation-manual", source_device_id="device-online")

    _insert_prefix(database, "prefix-current-run", discovered_devices=["device-online"], network_octet=16)
    _insert_observation(
        database,
        "prefix-current-run",
        "observation-current-run",
        source_device_id="device-online",
        collection_run_id="current-run",
    )

    for attempt in range(1, 4):
        assert prefix_service.age_missing_prefixes(
            collection_run_id="current-run",
            started_at="2026-10-02T00:00:00+00:00",
            covered_device_ids={"device-online"},
        ) == 1

    conn = database.get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, miss_count, is_active, status
            FROM prefixes
            WHERE id IN (?, ?, ?, ?, ?, ?)
            ORDER BY id
            """,
            (
                "prefix-current-run",
                "prefix-manual",
                "prefix-offline",
                "prefix-shared",
                "prefix-success",
                "prefix-unknown",
            ),
        ).fetchall()
    finally:
        conn.close()

    by_id = {row["id"]: dict(row) for row in rows}
    assert by_id["prefix-success"] == {
        "id": "prefix-success",
        "miss_count": 3,
        "is_active": 0,
        "status": "stale",
    }
    for prefix_id in (
        "prefix-current-run",
        "prefix-manual",
        "prefix-offline",
        "prefix-shared",
        "prefix-unknown",
    ):
        assert by_id[prefix_id]["miss_count"] == 0
        assert by_id[prefix_id]["is_active"] == 1
        assert by_id[prefix_id]["status"] == "active"


def test_age_missing_prefixes_without_coverage_is_a_noop(isolated_db) -> None:
    database = isolated_db["module"]
    _insert_prefix(database, "prefix-no-coverage", discovered_devices=["device-online"], network_octet=17)
    _insert_observation(database, "prefix-no-coverage", "observation-no-coverage", source_device_id="device-online")

    assert prefix_service.age_missing_prefixes(
        collection_run_id="no-coverage-run",
        started_at="2026-10-02T00:00:00+00:00",
    ) == 0

    conn = database.get_db_connection()
    try:
        row = conn.execute(
            "SELECT miss_count, is_active, status FROM prefixes WHERE id = ?",
            ("prefix-no-coverage",),
        ).fetchone()
    finally:
        conn.close()
    assert dict(row) == {"miss_count": 0, "is_active": 1, "status": "active"}


def test_job_ages_only_complete_success_owner_when_partial_and_offline_prefixes_are_missing(
    isolated_db, monkeypatch
) -> None:
    database = isolated_db["module"]
    _insert_device(database, "device-success")
    _insert_device(database, "device-partial")
    _insert_device(database, "device-offline", status="offline")

    for prefix_id, device_id, network_octet in (
        ("prefix-job-success", "device-success", 21),
        ("prefix-job-partial", "device-partial", 22),
        ("prefix-job-offline", "device-offline", 23),
    ):
        _insert_prefix(
            database,
            prefix_id,
            discovered_devices=[device_id],
            network_octet=network_octet,
            miss_count=2,
        )
        _insert_observation(
            database,
            prefix_id,
            f"observation-{prefix_id}",
            source_device_id=device_id,
        )

    def fake_discover(device, **_kwargs):
        status = "partial" if device["id"] == "device-partial" else "success"
        return {"created": 0, "updated": 0, "collection_status": status}

    monkeypatch.setattr(prefix_service, "discover_prefixes_for_device", fake_discover)

    result = prefix_service.run_prefix_discovery_job()

    assert result["successful_devices"] == 1
    assert result["partial_devices"] == 1
    assert result["failed_devices"] == 0
    assert result["aged_prefixes"] == 1

    conn = database.get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, miss_count, is_active, status
            FROM prefixes
            WHERE id IN (?, ?, ?)
            ORDER BY id
            """,
            ("prefix-job-offline", "prefix-job-partial", "prefix-job-success"),
        ).fetchall()
    finally:
        conn.close()
    by_id = {row["id"]: dict(row) for row in rows}
    assert by_id["prefix-job-success"] == {
        "id": "prefix-job-success",
        "miss_count": 3,
        "is_active": 0,
        "status": "stale",
    }
    for prefix_id in ("prefix-job-partial", "prefix-job-offline"):
        assert by_id[prefix_id]["miss_count"] == 2
        assert by_id[prefix_id]["is_active"] == 1
        assert by_id[prefix_id]["status"] == "active"
