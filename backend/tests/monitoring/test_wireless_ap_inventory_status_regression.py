from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import database
from services import librenms_wireless_rule_service as wireless
from services import snmp_hardware_probe_service as probe
from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT
from services.snmp_hardware_inventory_service import (
    list_hardware_metric_rows,
    list_hardware_sensors,
    render_hardware_metrics,
    upsert_discovery_run,
)
from services.snmp_hardware_poller_service import DISCOVERY_VERSION


def _serial_suffix(serial: str) -> str:
    octets = serial.encode("ascii")
    return ".".join(str(value) for value in (len(octets), *octets))


def _category(status: str = "success", *, complete: bool = True) -> dict[str, object]:
    return {
        "source_type": "librenms_mib_rule",
        "component_class": "wireless_access_point",
        "status": status,
        "coverage_complete": complete,
        "reason_code": "fixture_ap_snapshot",
        "reason": "PostgreSQL regression fixture",
    }


def _ap_state(
    serial: str,
    raw_state: str,
    description: str,
    value: int,
    observed_at: datetime,
    *,
    rule_key: str,
    ap_name: str | None = None,
    ap_model: str = "",
    ap_name_enriched: bool = True,
    ap_model_enriched: bool = True,
) -> dict[str, object]:
    resolved_name = ap_name or f"AP {serial}"
    return {
        "source_type": "librenms_mib_rule",
        "source_id": f"{rule_key}:wireless_access_point:state:{serial}",
        "component_class": "wireless_access_point",
        "measurement_type": "component_state",
        "series_variant": "ap-state",
        "index": [int(part) for part in _serial_suffix(serial).split(".")],
        "index_labels": {
            "ap_id": serial,
            "ap_serial": serial,
            "ap_name": resolved_name,
            "ap_model": ap_model,
        },
        "oid": "1.3.6.1.4.1.55555.100",
        "unit": "state",
        "states": {raw_state: {"generic": value, "descr": description}},
        "metadata": {
            "collection_version": DISCOVERY_VERSION,
            "rule_key": rule_key,
            "wireless_sensor_class": "ap-state",
            "poll_plan": {"kind": "snapshot_only"},
            "ap_name_enriched": ap_name_enriched,
            "ap_model_enriched": ap_model_enriched,
        },
        "sensor_name": resolved_name,
        "entity_name": resolved_name,
        "group_name": "wireless",
        "value": float(value),
        "raw_value": raw_state,
        "quality": "good",
        "sample_at": observed_at,
    }


def _ap_client(serial: str, observed_at: datetime, *, rule_key: str) -> dict[str, object]:
    return {
        "source_type": "librenms_mib_rule",
        "source_id": f"{rule_key}:wireless_access_point:clients:{serial}",
        "component_class": "wireless_access_point",
        "measurement_type": "wireless_sensor_value",
        "series_variant": "clients",
        "index": [int(part) for part in _serial_suffix(serial).split(".")],
        "index_labels": {"ap_id": serial, "ap_serial": serial},
        "oid": "1.3.6.1.4.1.55555.101",
        "unit": "count",
        "states": {},
        "metadata": {"rule_key": rule_key, "wireless_sensor_class": "clients"},
        "sensor_name": f"AP {serial} clients",
        "entity_name": f"AP {serial}",
        "group_name": "wireless",
        "value": 7.0,
        "raw_value": "7",
        "quality": "good",
        "sample_at": observed_at,
    }


def _seed_device(conn, device_id: str) -> None:
    conn.execute(
        """
        INSERT INTO devices (id, hostname, tenant_id, asset_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        (device_id, device_id, "tenant-default", f"asset-{device_id}"),
    )


def _stored_ap_state(conn, device_id: str, serial: str) -> dict[str, object]:
    return next(
        row for row in list_hardware_sensors(conn, device_id, component_class="wireless_access_point")
        if row["measurement_type"] == "component_state"
        and row["index_labels"].get("ap_serial") == serial
    )


def _probe_h3c(monkeypatch, rows_by_symbol: dict[tuple[str, str], list[tuple[str, str]]]):
    resolved: dict[tuple[str, str], str] = {}
    symbol_by_oid: dict[str, tuple[str, str]] = {}

    class Connection:
        def close(self) -> None:
            return None

    monkeypatch.setattr(wireless, "get_db_connection", Connection)

    def resolve(_conn, mib_path, symbol, *, cache=None):
        key = (mib_path.rsplit("/", 1)[-1], symbol)
        if key not in resolved:
            oid = f"1.3.6.1.4.1.55558.{len(resolved) + 1}"
            resolved[key] = oid
            symbol_by_oid[oid] = key
        return resolved[key]

    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)

    async def walk_many(_ip, _community, oids, _port, _version, *, walk_func=None):
        return {
            oid: SimpleNamespace(
                rows=rows_by_symbol.get(symbol_by_oid[oid], []),
                complete=True,
                reason="",
                octet_values={},
            )
            for oid in oids
        }

    monkeypatch.setattr(probe, "_walk_many", walk_many)
    return asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.80",
        "test-only-community",
        161,
        rule={"os_key": "comware", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "H3C"},
    ))


def test_h3c_connection_enum_uses_serial_and_keeps_unknown_states_unknown(monkeypatch):
    serials = (
        "SN-ONLINE", "SN-TRANSITION", "SN-TRANSIENT-DOWN",
        "SN-OFFLINE", "SN-FUTURE",
    )
    suffixes = {serial: _serial_suffix(serial) for serial in serials}
    rows = {
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APOperationStatus"): [
            (suffixes["SN-ONLINE"], "run(5)"),
            (suffixes["SN-TRANSITION"], "download(3)"),
            (suffixes["SN-TRANSIENT-DOWN"], "download(3)"),
            (suffixes["SN-OFFLINE"], "run(5)"),
            (suffixes["SN-FUTURE"], "run(5)"),
        ],
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APConnectionType"): [
            (suffixes["SN-ONLINE"], "master(1)"),
            (suffixes["SN-TRANSITION"], "slave(2)"),
            (suffixes["SN-TRANSIENT-DOWN"], "notAvailable(3)"),
            (suffixes["SN-OFFLINE"], "notAvailable(3)"),
            (suffixes["SN-FUTURE"], "backup(4)"),
        ],
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPName"): [
            (suffixes["SN-ONLINE"], "AP online"),
            (suffixes["SN-TRANSITION"], "AP transition"),
        ],
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPModelName"): [
            (suffixes["SN-ONLINE"], "WA6320-HCL"),
            (suffixes["SN-TRANSITION"], "WA6320-HCL"),
        ],
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APIPAddress"): [
            (suffixes["SN-ONLINE"], "192.0.2.81"),
        ],
    }
    result = _probe_h3c(monkeypatch, rows)
    ap_states = {
        item["index_labels"]["ap_serial"]: item
        for item in result["sensors"]
        if item["component_class"] == "wireless_access_point"
        and item["measurement_type"] == "component_state"
    }

    assert set(ap_states) == set(serials)
    assert ap_states["SN-ONLINE"]["states"]["run(5)"]["descr"] == "online"
    assert ap_states["SN-TRANSITION"]["raw_value"] == "download(3)"
    assert ap_states["SN-TRANSITION"]["states"]["download(3)"]["descr"] == "download"
    assert ap_states["SN-TRANSIENT-DOWN"]["states"]["download(3)"]["descr"] == "download"
    assert ap_states["SN-OFFLINE"]["raw_value"] == "notAvailable(3)"
    assert ap_states["SN-OFFLINE"]["states"]["notAvailable(3)"]["descr"] == "disconnected"
    assert ap_states["SN-OFFLINE"]["value"] == 2.0
    assert ap_states["SN-FUTURE"]["states"]["backup(4)"]["descr"] == "unknown"
    assert ap_states["SN-FUTURE"]["value"] == 3.0
    assert all(item["metadata"]["poll_plan"]["kind"] == "snapshot_only" for item in ap_states.values())
    ap_result = next(
        item for item in result["category_results"]
        if item["component_class"] == "wireless_access_point"
    )
    assert ap_result["coverage_complete"] is True


@pytest.mark.parametrize(
    "rule_key",
    ["wireless_h3c_comware", "wireless_huawei_vrp", "wireless_cisco_wlc"],
)
def test_complete_ap_absence_is_not_reported_and_recovery_reuses_identity(isolated_db, rule_key, monkeypatch):
    conn = database.get_db_connection()
    try:
        device_id = f"ap-availability-{rule_key}"
        _seed_device(conn, device_id)
        start = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
        ap_a = _ap_state("SN-A", "run(5)", "online", 0, start, rule_key=rule_key)
        ap_b = _ap_state(
            "SN-B", "notAvailable(3)", "disconnected", 2, start,
            rule_key=rule_key,
            ap_name="AP-B-Original" if rule_key == "wireless_h3c_comware" else None,
            ap_model="WA6320-HCL" if rule_key == "wireless_h3c_comware" else "",
        )
        # Existing inventory rows may predate snapshot-only AP state polling.
        # A complete snapshot that loses the AP identity must migrate that
        # stale direct poll plan so it cannot overwrite `not_reported`.
        ap_b["metadata"]["poll_plan"] = {
            "kind": "direct",
            "oid": ap_b["oid"],
            "index": ".".join(str(part) for part in ap_b["index"]),
        }
        client_b = _ap_client("SN-B", start, rule_key=rule_key)
        upsert_discovery_run(
            conn,
            device_id,
            "ap-inventory-1",
            "wireless-fixture-v1",
            [ap_a, ap_b, client_b],
            [_category()],
            start,
        )
        conn.commit()

        if rule_key == "wireless_h3c_comware":
            # The H3C current-AP name/model table only covers running APs.
            # When an AP disconnects, retain its last enriched identity labels.
            disconnected_at = start + timedelta(seconds=30)
            fallback_name = _ap_state(
                "SN-B", "notAvailable(3)", "disconnected", 2, disconnected_at,
                rule_key=rule_key,
                ap_name="AP SN-B",
                ap_model="",
                ap_name_enriched=False,
                ap_model_enriched=False,
            )
            upsert_discovery_run(
                conn,
                device_id,
                "ap-inventory-disconnected-enrichment",
                "wireless-fixture-v1",
                [
                    _ap_state("SN-A", "run(5)", "online", 0, disconnected_at, rule_key=rule_key),
                    fallback_name,
                ],
                [_category()],
                disconnected_at,
            )
            disconnected = _stored_ap_state(conn, device_id, "SN-B")
            assert disconnected["index_labels"]["ap_name"] == "AP-B-Original"
            assert disconnected["index_labels"]["ap_model"] == "WA6320-HCL"
            assert disconnected["sensor_name"] == "AP-B-Original"
            assert disconnected["entity_name"] == "AP-B-Original"

        initial_export = render_hardware_metrics(
            list_hardware_metric_rows(conn),
            {"tenant_id": "tenant-default", "asset_id": f"asset-{device_id}", "device_id": device_id},
        )
        assert 'state_description="disconnected"' in initial_export

        # Incomplete, partial, and failed snapshots cannot replace the AP state.
        for offset, status, complete in (
            (1, "partial", False),
            (2, "success", False),
            (3, "failed", False),
        ):
            candidate = _ap_state(
                "SN-B", "run(5)", "online", 0, start + timedelta(minutes=offset), rule_key=rule_key,
            )
            upsert_discovery_run(
                conn,
                device_id,
                f"ap-inventory-{offset + 1}",
                "wireless-fixture-v1",
                [candidate] if status != "failed" else [],
                [_category(status, complete=complete)],
                start + timedelta(minutes=offset),
            )
            assert _stored_ap_state(conn, device_id, "SN-B")["last_raw_value"] == "notAvailable(3)"

        # One complete snapshot misses SN-B. Its state identity remains enabled
        # even though the ordinary AP client sensor is absent from export.
        observed = start + timedelta(minutes=4)
        upsert_discovery_run(
            conn,
            device_id,
            "ap-inventory-5",
            "wireless-fixture-v1",
            [_ap_state("SN-A", "run(5)", "online", 0, observed, rule_key=rule_key)],
            [_category()],
            observed,
        )
        missing_state = _stored_ap_state(conn, device_id, "SN-B")
        assert missing_state["last_raw_value"] == "not_reported"
        assert missing_state["lifecycle_status"] == "active"
        assert missing_state["discovery_status"] == "not_present"
        assert missing_state["enabled"] is True
        assert missing_state["missing_success_count"] == 1
        assert missing_state["last_success"] == observed
        assert missing_state["metadata"]["poll_plan"] == {"kind": "snapshot_only"}
        assert missing_state["metadata"]["collection_version"] == DISCOVERY_VERSION

        persisted_samples: list[dict[str, object]] = []
        monkeypatch.setattr(
            probe,
            "_persist_hardware_sensor_samples",
            lambda batch: persisted_samples.extend(batch),
        )

        async def unexpected_walk(*_args, **_kwargs):
            raise AssertionError("a missing AP must not be polled through its stale row OID")

        missing_state.update({"device_id": device_id, "enabled": True})
        sample_result = asyncio.run(probe.poll_hardware_inventory(
            "192.0.2.83", "test-only-community", 161, "2c",
            [missing_state], walk_func=unexpected_walk,
        ))
        assert sample_result == {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
        assert persisted_samples == []
        assert _stored_ap_state(conn, device_id, "SN-B")["last_raw_value"] == "not_reported"

        # Exercise the same version gate used by the production Grafana exporter.
        export_rows = list_hardware_metric_rows(conn, collection_version=DISCOVERY_VERSION)
        ap_state_rows = [
            row for row in export_rows
            if row["device_id"] == device_id
            and row["component_class"] == "wireless_access_point"
            and row["measurement_type"] == "component_state"
        ]
        assert len(ap_state_rows) == 2
        assert not any(
            row["device_id"] == device_id and row["measurement_type"] == "wireless_sensor_value"
            for row in export_rows
        )
        exported = render_hardware_metrics(
            export_rows,
            {"tenant_id": "tenant-default", "asset_id": f"asset-{device_id}", "device_id": device_id},
        )
        assert 'raw_state="not_reported"' in exported
        assert 'state_description="not_reported"' in exported

        # An authoritative empty snapshot also preserves known AP identities.
        empty_time = start + timedelta(minutes=5)
        upsert_discovery_run(
            conn,
            device_id,
            "ap-inventory-6",
            "wireless-fixture-v1",
            [],
            [_category("not_found", complete=True)],
            empty_time,
        )
        assert _stored_ap_state(conn, device_id, "SN-A")["last_raw_value"] == "not_reported"
        assert _stored_ap_state(conn, device_id, "SN-B")["last_raw_value"] == "not_reported"

        # The same serial index is upserted on recovery and becomes online again.
        restored_at = start + timedelta(minutes=6)
        upsert_discovery_run(
            conn,
            device_id,
            "ap-inventory-7",
            "wireless-fixture-v1",
            [
                _ap_state("SN-A", "run(5)", "online", 0, restored_at, rule_key=rule_key),
                _ap_state(
                    "SN-B", "run(5)", "online", 0, restored_at,
                    rule_key=rule_key,
                    ap_name="AP-B-Recovered" if rule_key == "wireless_h3c_comware" else None,
                    ap_model="WA6320-HCL" if rule_key == "wireless_h3c_comware" else "",
                ),
            ],
            [_category()],
            restored_at,
        )
        restored = _stored_ap_state(conn, device_id, "SN-B")
        assert restored["last_raw_value"] == "run(5)"
        assert restored["states"]["run(5)"]["descr"] == "online"
        assert restored["lifecycle_status"] == "active"
        assert restored["discovery_status"] == "present"
        assert restored["enabled"] is True
        assert restored["missing_success_count"] == 0
        assert restored["last_missing_run_id"] == ""
    finally:
        conn.close()


def test_snapshot_only_ap_state_is_skipped_by_inventory_poller(monkeypatch):
    samples: list[dict[str, object]] = []

    def persist(batch):
        samples.extend(batch)

    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", persist)

    async def unexpected_walk(*_args, **_kwargs):
        raise AssertionError("snapshot-only AP state must not issue an SNMP poll")

    state = _ap_state(
        "SN-SNAPSHOT", "not_reported", "not_reported", 3,
        datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc),
        rule_key="wireless_h3c_comware",
    )
    state.update({"device_id": "snapshot-only-device", "sensor_key": "snapshot-only-key", "enabled": True})
    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.82", "test-only-community", 161, "2c", [state], walk_func=unexpected_walk,
    ))

    assert result == {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert samples == []
