from __future__ import annotations

from datetime import datetime, timedelta, timezone

import database
from database.migrations.m0260_snmp_hardware_inventory import upgrade as upgrade_hardware_inventory
from services.snmp_hardware_inventory_service import (
    build_sensor_key,
    list_hardware_capabilities,
    list_hardware_discovery_runs,
    list_hardware_metric_rows,
    list_hardware_sensors,
    record_sensor_sample,
    render_hardware_metrics,
    upsert_discovery_run,
)


def _seed_device(conn, device_id: str = "hardware-inventory-device") -> None:
    conn.execute(
        """
        INSERT INTO devices (id, hostname, tenant_id, asset_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        (device_id, "edge-01", "tenant-default", "asset-edge-01"),
    )
    conn.commit()


def _category(source_type: str, component_class: str, *, status: str = "success", complete: bool = True, reason: str = ""):
    return {
        "source_type": source_type,
        "component_class": component_class,
        "status": status,
        "coverage_complete": complete,
        "reason_code": "" if status == "success" else "walk_timeout",
        "reason": reason,
    }


def _sensor(*, component_class: str = "temperature", measurement_type: str = "temperature_celsius", index=None, **overrides):
    data = {
        "source_type": "entity_sensor",
        "source_id": "ENTITY-SENSOR-MIB",
        "component_class": component_class,
        "measurement_type": measurement_type,
        "index": {"entPhysicalIndex": 9, "sensorIndex": 2} if index is None else index,
        "index_labels": {"entPhysicalIndex": "9", "sensorIndex": "2"},
        "oid": "1.3.6.1.4.1.999.1.4.1.1.9",
        "unit": "celsius",
        "scale": 0.1,
        "offset": 0,
        "states": {},
        "thresholds": {"high": 80},
        "metadata": {"source": "fixture"},
        "sensor_name": "Board inlet",
        "entity_name": "Line card 1",
        "group_name": "chassis",
    }
    data.update(overrides)
    return data


def test_sensor_key_uses_canonical_full_index_and_measurement_identity() -> None:
    first = build_sensor_key("vendor_adapter", "cpu", "cpu_usage_percent", {"slot": 1, "core": 3})
    reordered = build_sensor_key("vendor_adapter", "cpu", "cpu_usage_percent", {"core": 3, "slot": 1})
    different_core = build_sensor_key("vendor_adapter", "cpu", "cpu_usage_percent", {"slot": 1, "core": 4})
    different_measurement = build_sensor_key("vendor_adapter", "cpu", "cpu_5m_percent", {"slot": 1, "core": 3})
    one_minute = build_sensor_key("vendor_adapter", "cpu", "cpu_usage_percent", {"slot": 1, "core": 3}, "1m")
    five_minutes = build_sensor_key("vendor_adapter", "cpu", "cpu_usage_percent", {"slot": 1, "core": 3}, "5m")

    assert first == reordered
    assert first != different_core
    assert first != different_measurement
    assert one_minute != five_minutes


def test_component_state_exports_raw_description_and_explicit_presence():
    state = _sensor(
        component_class="fan_state",
        measurement_type="component_state",
        index=[1],
        states=[
            {"value": 1, "descr": "active", "generic": 0},
            {"value": 3, "descr": "not-install", "generic": 3},
        ],
        index_labels={
            "ap_id": "AP-ID-1",
            "ap_name": "AP_12",
            "ap_model": "WA6320-HCL",
            "radio_id": "1",
        },
        metadata={"window": "15m"},
        last_quality="good",
        last_value=3,
        last_raw_value="3",
        rule_version="librenms-commit-1",
        discovery_status="not_present",
    )
    text = render_hardware_metrics([state], {"asset_id": "asset-1", "device_id": "device-1"})

    assert 'nexora_hw_component_state{' in text
    assert 'raw_state="3"' in text
    assert 'state_description="not-install"' in text
    assert 'rule_version="librenms-commit-1"' in text
    info_line = next(line for line in text.splitlines() if line.startswith("nexora_hw_sensor_info{"))
    assert 'ap_name="AP_12"' in info_line
    assert 'group="chassis"' in info_line
    assert 'rule_version="librenms-commit-1"' in info_line
    assert "index_labels=" not in info_line
    assert "group_name=" not in info_line
    assert 'window="15m"' not in info_line
    assert 'window="15m"' in next(
        line for line in text.splitlines() if line.startswith("nexora_hw_component_state{")
    )
    assert 'nexora_hw_component_present{' in text
    presence_line = next(line for line in text.splitlines() if line.startswith("nexora_hw_component_present{"))
    assert 'state_description="not-install"' in presence_line
    assert presence_line.endswith(" 0")


def test_hardware_inventory_migration_is_idempotent_postgresql(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        upgrade_hardware_inventory(conn.cursor(), use_pg=True)
        upgrade_hardware_inventory(conn.cursor(), use_pg=True)
        conn.commit()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            ).fetchall()
        }
        assert {
            "snmp_hardware_discovery_runs",
            "snmp_hardware_sensors",
            "snmp_hardware_capabilities",
        } <= tables
        unique_definitions = {
            row[0]
            for row in conn.execute(
                """
                SELECT pg_get_constraintdef(oid)
                  FROM pg_constraint
                 WHERE conrelid = 'snmp_hardware_sensors'::regclass AND contype = 'u'
                """
            ).fetchall()
        }
        assert any("device_id, source_type, component_class, measurement_type, index_json, series_variant" in item for item in unique_definitions)
    finally:
        conn.close()


def test_same_cpu_index_keeps_independent_one_and_five_minute_series(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn, "hardware-window-device")
        observed_at = datetime(2026, 9, 29, 2, 0, tzinfo=timezone.utc)
        sensors = [
            _sensor(
                source_type="librenms", source_id="cpu-window-fixture",
                component_class="processor", measurement_type="cpu_usage_percent",
                index=[1], oid="1.3.6.1.4.1.999.2.1", unit="percent",
                metadata={"window": window}, sensor_name="CPU 1",
                value=value, raw_value=str(value), quality="good", sample_at=observed_at,
            )
            for window, value in (("1m", 31), ("5m", 28))
        ]

        upsert_discovery_run(
            conn,
            "hardware-window-device",
            "window-run-1",
            "rules-1",
            sensors,
            [_category("librenms", "processor")],
            observed_at,
        )
        conn.commit()

        stored = list_hardware_sensors(conn, "hardware-window-device", include_retired=False)
        assert len(stored) == 2
        assert {row["series_variant"] for row in stored} == {"1m", "5m"}
        assert len({row["sensor_key"] for row in stored}) == 2
        exposition = render_hardware_metrics(stored, {
            "tenant_id": "tenant-default",
            "asset_id": "asset-edge-01",
            "device_id": "hardware-window-device",
        })
        assert 'window="1m"' in exposition
        assert 'window="5m"' in exposition
    finally:
        conn.close()


def test_native_samples_use_native_identity_and_order_by_sample_time(isolated_db) -> None:
    conn = database.get_db_connection()
    device_id = "hardware-native-device"
    try:
        _seed_device(conn, device_id)
        base_at = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)

        def native_cpu(value: float, sample_at: datetime):
            return _sensor(
                source_type="librenms_native",
                source_id="processor:3",
                data_origin="librenms_native",
                native_instance_id="lnms-1",
                native_device_id="17",
                native_entity_id="processor:3",
                component_class="processor",
                measurement_type="cpu_usage_percent",
                index={
                    "instance_id": "lnms-1",
                    "native_device_id": "17",
                    "row_kind": "processor",
                    "native_row_id": "3",
                },
                oid="",
                unit="%",
                scale=1,
                offset=0,
                metadata={"window": "unknown", "poll_interval_seconds": 300},
                value=value,
                raw_value=str(value),
                quality="good",
                sample_at=sample_at,
            )

        for run_id, request_at, value, sample_at in (
            ("native-run-1", base_at + timedelta(minutes=10), 37, base_at),
            ("native-run-2", base_at + timedelta(minutes=20), 42, base_at + timedelta(minutes=5)),
            # A fresh API read may contain a lagging upstream row. It must not
            # replace the newer LibreNMS sample already projected.
            ("native-run-3", base_at + timedelta(minutes=30), 8, base_at + timedelta(minutes=3)),
        ):
            upsert_discovery_run(
                conn,
                device_id,
                run_id,
                "librenms-26.9.1",
                [native_cpu(value, sample_at)],
                [_category("librenms_native", "processor")],
                observed_at=request_at,
            )

        stored = list_hardware_sensors(conn, device_id, component_class="processor")
        assert len(stored) == 1
        row = stored[0]
        assert row["data_origin"] == "librenms_native"
        assert row["native_instance_id"] == "lnms-1"
        assert row["native_device_id"] == "17"
        assert row["native_entity_id"] == "processor:3"
        assert row["last_value"] == 42
        assert row["last_sample_at"] == base_at + timedelta(minutes=5)
        assert row["last_success"] == base_at + timedelta(minutes=5)
        metrics = render_hardware_metrics(stored, {"device_id": device_id})
        cpu_line = next(line for line in metrics.splitlines() if line.startswith("nexora_hw_cpu_usage_percent{"))
        assert 'data_origin="librenms_native"' in cpu_line
        assert 'native_instance_id="lnms-1"' in cpu_line
        assert cpu_line.endswith(" 42")
    finally:
        conn.close()


def test_native_sample_without_lastupdate_does_not_borrow_request_time(isolated_db) -> None:
    conn = database.get_db_connection()
    device_id = "hardware-native-unknown-time"
    try:
        _seed_device(conn, device_id)
        request_at = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)
        sensor = _sensor(
            source_type="librenms_native",
            source_id="mempool:4",
            data_origin="librenms_native",
            native_instance_id="lnms-1",
            native_device_id="17",
            native_entity_id="mempool:4",
            component_class="mempool",
            measurement_type="memory_usage_percent",
            index={"instance_id": "lnms-1", "native_device_id": "17", "row_kind": "mempool", "native_row_id": "4"},
            oid="",
            unit="%",
            scale=1,
            value=62,
            raw_value="62",
            quality="good",
            sample_at=None,
        )
        upsert_discovery_run(
            conn,
            device_id,
            "native-unknown-time-run",
            "librenms-26.9.1",
            [sensor],
            [_category("librenms_native", "mempool")],
            observed_at=request_at,
        )
        stored = list_hardware_sensors(conn, device_id, component_class="mempool")
        assert len(stored) == 1
        assert stored[0]["last_value"] is None
        assert stored[0]["last_raw_value"] is None
        assert stored[0]["last_quality"] == "missing"
        assert stored[0]["last_success"] is None
        assert stored[0]["last_sample_at"] is None
        assert stored[0]["last_seen"] == request_at
    finally:
        conn.close()


def test_partial_failure_preserves_inventory_and_complete_absence_retires_after_two_runs(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn)
        t0 = datetime(2026, 9, 29, 2, 0, tzinfo=timezone.utc)
        initial = _sensor(value=42.5, raw_value=425, quality="good", sample_at=t0)
        first = upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-1",
            "catalog-1",
            [initial],
            [_category("entity_sensor", "temperature")],
            t0,
            discovery_version="discover-1",
            artifact_version="artifact-1",
        )
        conn.commit()
        assert first["results"][0]["active_sensor_count"] == 1
        rows = list_hardware_sensors(conn, "hardware-inventory-device")
        assert len(rows) == 1
        sensor_key = rows[0]["sensor_key"]
        assert rows[0]["tenant_id"] == "tenant-default"
        assert rows[0]["asset_id"] == "asset-edge-01"
        assert rows[0]["index"] == {"entPhysicalIndex": 9, "sensorIndex": 2}
        assert rows[0]["first_seen"] == rows[0]["last_seen"]
        assert rows[0]["last_success"] == t0
        assert rows[0]["last_value"] == 42.5
        assert rows[0]["last_raw_value"] == "425"
        assert rows[0]["last_quality"] == "good"

        # Partial coverage, a failed category, and an incomplete success are
        # recorded as distinct outcomes and cannot retire the known sensor.
        upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-2",
            "catalog-1",
            [],
            [_category("entity_sensor", "temperature", status="partial", complete=False, reason="one table timed out")],
            t0.replace(minute=5),
        )
        upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-3",
            "catalog-1",
            [],
            [_category("vendor_adapter", "fan", status="failed", complete=False, reason="SNMP timeout")],
            t0.replace(minute=10),
        )
        upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-4",
            "catalog-1",
            [],
            [_category("entity_sensor", "temperature", status="success", complete=False)],
            t0.replace(minute=15),
        )
        row = list_hardware_sensors(conn, "hardware-inventory-device")[0]
        assert row["lifecycle_status"] == "active"
        assert row["enabled"] is True
        assert row["last_value"] == 42.5
        conn.commit()

        # The first complete absence only marks pending retirement.
        first_absence = upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-5",
            "catalog-1",
            [],
            [_category("entity_sensor", "temperature")],
            t0.replace(minute=20),
        )
        assert first_absence["results"][0]["active_sensor_count"] == 0
        row = list_hardware_sensors(conn, "hardware-inventory-device")[0]
        assert row["lifecycle_status"] == "pending_retirement"
        assert row["missing_success_count"] == 1
        conn.commit()

        # Replaying the same successful category run is idempotent and does not
        # count as a second removal confirmation.
        replay = upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-5",
            "catalog-1",
            [],
            [_category("entity_sensor", "temperature")],
            t0.replace(minute=20),
        )
        assert replay["replayed_scopes"] == [{"source_type": "entity_sensor", "component_class": "temperature"}]
        assert list_hardware_sensors(conn, "hardware-inventory-device")[0]["missing_success_count"] == 1
        conn.commit()

        upsert_discovery_run(
            conn,
            "hardware-inventory-device",
            "run-6",
            "catalog-1",
            [],
            [_category("entity_sensor", "temperature")],
            t0.replace(minute=25),
        )
        row = list_hardware_sensors(conn, "hardware-inventory-device")[0]
        assert row["lifecycle_status"] == "retired"
        assert row["enabled"] is False
        assert row["missing_success_count"] == 2
        runs = list_hardware_discovery_runs(conn, "hardware-inventory-device")
        failed = next(run for run in runs if run["source_type"] == "vendor_adapter")
        assert failed["status"] == "failed"
        assert failed["reason"] == "SNMP timeout"
        capability = next(item for item in list_hardware_capabilities(conn, "hardware-inventory-device") if item["source_type"] == "vendor_adapter")
        assert capability["last_status"] == "failed"
        assert capability["active_sensor_count"] == 0
        conn.commit()
    finally:
        conn.close()


def test_measurement_upsert_sample_update_and_prometheus_rendering(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn, "hardware-render-device")
        now = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
        cpu = _sensor(
            component_class="cpu",
            measurement_type="cpu_usage_percent",
            index={"processor": 1, "window": "1m"},
            oid="1.3.6.1.4.1.9.9.109.1.1.1.1.5.1",
            unit="percent",
            scale=1,
            sensor_name='CPU "1"',
            value=23.0,
            raw_value="23",
            quality="good",
            sample_at=now,
            metadata={"raw_error": "must not become a Prometheus label", "window": "5m"},
        )
        outcome = upsert_discovery_run(
            conn,
            "hardware-render-device",
            "render-run-1",
            "rules-v3",
            [cpu],
            [_category("entity_sensor", "cpu")],
            now,
        )
        assert outcome["results"][0]["active_sensor_count"] == 1
        conn.commit()
        rows = list_hardware_sensors(conn, "hardware-render-device", component_class="cpu")
        assert rows[0]["tenant_id"] == "tenant-default"
        assert rows[0]["asset_id"] == "asset-edge-01"
        key = rows[0]["sensor_key"]
        assert record_sensor_sample(conn, "hardware-render-device", key, 31.0, 30, "good", now.replace(minute=2))
        conn.commit()
        refreshed = list_hardware_sensors(conn, "hardware-render-device")[0]
        assert refreshed["last_value"] == 31
        assert refreshed["last_raw_value"] == "30"
        assert refreshed["last_success"].minute == 2

        # Render from the freshly persisted record so the value/quality contract
        # is checked against the PostgreSQL row, not only the input fixture.
        text = render_hardware_metrics(list_hardware_sensors(conn, "hardware-render-device"), {
            "tenant_id": "tenant-default",
            "asset_id": "asset-edge-01",
            "device_id": "hardware-render-device",
            "hostname": "edge-01",
            "site_name": 'North "DC"',
        })
        cpu_sample = next(line for line in text.splitlines() if line.startswith("nexora_hw_cpu_usage_percent{"))
        assert 'asset_id="asset-edge-01"' in cpu_sample
        assert 'device_id="hardware-render-device"' in cpu_sample
        assert 'measurement_type="cpu_usage_percent"' in cpu_sample
        assert 'sensor_key="' in cpu_sample
        assert 'window="5m"' in text
        assert " 31\n" in text
        assert 'site_name="North \\"DC\\""' in text
        assert 'quality="good"' in text
        assert "nexora_hw_sensor_last_success_timestamp_seconds" in text
        assert "must not become a Prometheus label" not in text

        assert not record_sensor_sample(conn, "hardware-render-device", "missing-sensor-key", 1, 1, "good", now)
    finally:
        conn.close()


def test_metric_query_skips_only_types_the_prometheus_renderer_omits(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        device_id = "hardware-metric-export-device"
        _seed_device(conn, device_id)
        at = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
        component_types = [
            ("cpu", "cpu_usage_percent"),
            ("voltage", "voltage_volts"),
            ("current", "current_amperes"),
            ("generic", "sensor_value"),
            ("wireless", "wireless_sensor_value"),
        ]
        sensors = [
            _sensor(
                component_class=component_class,
                measurement_type=measurement_type,
                index={"entPhysicalIndex": index},
                quality="good",
                value=1,
                raw_value="1",
                sample_at=at,
                metadata={"collection_version": "test-version"},
            )
            for index, (component_class, measurement_type) in enumerate(component_types, start=1)
        ]
        categories = [
            _category("entity_sensor", component_class)
            for component_class, _measurement_type in component_types
        ]
        upsert_discovery_run(
            conn,
            device_id,
            "metric-export-run",
            "rules-v3",
            sensors,
            categories,
            at,
            discovery_version="test-version",
        )
        conn.commit()

        complete_sensor_rows = list_hardware_sensors(conn, device_id)
        export_sensor_rows = list_hardware_metric_rows(conn, collection_version="test-version")
        labels = {"tenant_id": "tenant-default", "asset_id": "asset-edge-01", "device_id": device_id}

        assert {row["measurement_type"] for row in complete_sensor_rows} == {
            measurement_type for _component_class, measurement_type in component_types
        }
        assert {row["measurement_type"] for row in export_sensor_rows} == {
            "cpu_usage_percent",
            "wireless_sensor_value",
        }
        assert render_hardware_metrics(complete_sensor_rows, labels) == render_hardware_metrics(
            export_sensor_rows,
            labels,
        )
    finally:
        conn.close()


def test_same_complete_index_in_different_component_classes_is_distinct(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn, "hardware-class-device")
        at = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)
        sensors = [
            _sensor(component_class="fan", measurement_type="component_state", index={"index": 1}, oid="1.3.6.1.1.1.1"),
            _sensor(component_class="power_supply", measurement_type="component_state", index={"index": 1}, oid="1.3.6.1.1.1.2"),
        ]
        run = upsert_discovery_run(
            conn,
            "hardware-class-device",
            "class-run",
            "rules-v1",
            sensors,
            [_category("entity_sensor", "fan"), _category("entity_sensor", "power_supply")],
            at,
        )
        assert [item["active_sensor_count"] for item in run["results"]] == [1, 1]
        rows = list_hardware_sensors(conn, "hardware-class-device")
        assert len(rows) == 2
        assert len({row["sensor_key"] for row in rows}) == 2
    finally:
        conn.close()


def test_out_of_order_discovery_and_samples_cannot_revert_newer_state(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn, "hardware-order-device")
        t0 = datetime(2026, 9, 29, 5, 0, tzinfo=timezone.utc)
        sensor = _sensor(value=10, raw_value=10, quality="good", sample_at=t0)
        upsert_discovery_run(
            conn,
            "hardware-order-device",
            "order-run-1",
            "rules-v1",
            [sensor],
            [_category("entity_sensor", "temperature")],
            t0,
        )
        conn.commit()
        saved = list_hardware_sensors(conn, "hardware-order-device")[0]
        key = saved["sensor_key"]

        assert record_sensor_sample(conn, "hardware-order-device", key, 20, 20, "good", t0.replace(minute=10))
        conn.commit()
        assert record_sensor_sample(conn, "hardware-order-device", key, 5, 5, "good", t0.replace(minute=5))
        newer = list_hardware_sensors(conn, "hardware-order-device")[0]
        assert newer["last_value"] == 20
        assert newer["last_raw_value"] == "20"

        newer_definition = _sensor(
            value=20,
            raw_value=20,
            quality="good",
            sample_at=t0.replace(minute=10),
        )
        upsert_discovery_run(
            conn,
            "hardware-order-device",
            "order-run-2",
            "rules-v1",
            [newer_definition],
            [_category("entity_sensor", "temperature")],
            t0.replace(minute=12),
        )

        stale_run = upsert_discovery_run(
            conn,
            "hardware-order-device",
            "order-run-old",
            "rules-v1",
            [],
            [_category("entity_sensor", "temperature")],
            t0.replace(minute=8),
        )
        assert stale_run["stale_scopes"] == [{"source_type": "entity_sensor", "component_class": "temperature"}]
        current = list_hardware_sensors(conn, "hardware-order-device")[0]
        assert current["lifecycle_status"] == "active"
        assert current["last_value"] == 20
        capability = list_hardware_capabilities(conn, "hardware-order-device")[0]
        assert capability["last_run_id"] == "order-run-2"
    finally:
        conn.close()


def test_explicit_not_present_is_distinct_from_failed_and_can_recover(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        _seed_device(conn, "hardware-presence-device")
        at = datetime(2026, 9, 29, 6, 0, tzinfo=timezone.utc)
        sensor = _sensor(source_type="vendor_adapter", component_class="fan", measurement_type="component_state", index={"fan": 1}, oid="1.3.6.1.4.1.9.9.13.1.3.1.3.1")
        upsert_discovery_run(
            conn,
            "hardware-presence-device",
            "presence-run-1",
            "rules-v1",
            [sensor],
            [_category("vendor_adapter", "fan")],
            at,
        )
        not_present = dict(sensor, presence_status="not_present")
        upsert_discovery_run(
            conn,
            "hardware-presence-device",
            "presence-run-2",
            "rules-v1",
            [not_present],
            [_category("vendor_adapter", "fan")],
            at.replace(minute=5),
        )
        saved = list_hardware_sensors(conn, "hardware-presence-device")[0]
        assert saved["discovery_status"] == "not_present"
        assert saved["lifecycle_status"] == "active"
        assert saved["enabled"] is False
        assert saved["missing_success_count"] == 0

        upsert_discovery_run(
            conn,
            "hardware-presence-device",
            "presence-run-3",
            "rules-v1",
            [sensor],
            [_category("vendor_adapter", "fan")],
            at.replace(minute=10),
        )
        recovered = list_hardware_sensors(conn, "hardware-presence-device")[0]
        assert recovered["discovery_status"] == "present"
        assert recovered["lifecycle_status"] == "active"
        assert recovered["enabled"] is True
    finally:
        conn.close()


def test_renderer_uses_explicit_cpu_window_or_unknown_without_inference() -> None:
    base = {
        "device_id": "device-1",
        "asset_id": "asset-1",
        "tenant_id": "tenant-1",
        "sensor_key": "cpu-sensor",
        "source_type": "vendor_adapter",
        "component_class": "cpu",
        "measurement_type": "cpu_usage_percent",
        "lifecycle_status": "active",
        "enabled": True,
        "last_value": 25,
        "last_quality": "good",
        "last_success": None,
        "index_labels": {"processor": "1"},
    }
    labels = {"hostname": "router-1"}

    unknown_text = render_hardware_metrics([dict(base, metadata={})], labels)
    explicit_text = render_hardware_metrics([dict(base, metadata={"window": "5m"})], labels)

    assert 'window="unknown"' in unknown_text
    assert 'window="5m"' in explicit_text
    assert 'window="1m"' not in unknown_text
    assert 'window="5m"' in next(line for line in explicit_text.splitlines() if line.startswith("nexora_hw_cpu_usage_percent{"))
