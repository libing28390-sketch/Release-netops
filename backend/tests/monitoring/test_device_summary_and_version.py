import uuid

import pytest
import yaml

from api.devices import read_devices_summary
from database import get_db_connection
from database.migrations.m0274_add_device_version_column import upgrade
from services.monitoring_compiler import CompileError, _parse_variant_oid_config
from services.platform_identification_service import _persist_discovered_version


def test_summary_counts_over_200_across_historical_tenants_and_respects_asset_type(isolated_db):
    connection = get_db_connection()
    try:
        connection.execute("DELETE FROM devices")
        server_asset = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO physical_assets (id, asset_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (server_asset, "server", "2026-10-05", "2026-10-05"),
        )
        for index in range(313):
            connection.execute(
                "INSERT INTO devices (id, hostname, platform, status, tenant_id) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), f"summary-network-{index}", "h3c_comware", "online", "summary-a"),
            )
        connection.execute(
            "INSERT INTO devices (id, hostname, status, tenant_id) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "summary-other-tenant", "offline", "summary-b"),
        )
        connection.execute(
            "INSERT INTO devices (id, hostname, status, tenant_id, asset_id) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "summary-server", "pending", "summary-a", server_asset),
        )
        connection.commit()
    finally:
        connection.close()

    viewer = {"role": "Viewer", "tenant_id": "summary-a"}
    summary = read_devices_summary(asset_type="network_device", user=viewer)
    assert summary == {
        "total": 314, "online": 313, "offline": 1, "pending": 0, "unknown": 0,
        "by_platform": [
            {"platform": "h3c_comware", "count": 313},
            {"platform": "unknown", "count": 1},
        ],
    }
    assert read_devices_summary(asset_type="all", user=viewer)["total"] == 315
    admin = read_devices_summary(asset_type="network_device", user={"role": "Administrator"})
    assert admin["total"] == 314 and admin["offline"] == 1


def test_discovered_version_does_not_update_nonexistent_asset_version(isolated_db):
    connection = get_db_connection()
    device_id, asset_id = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        connection.execute(
            "INSERT INTO physical_assets (id, asset_type, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (asset_id, "network_device", "2026-10-05", "2026-10-05"),
        )
        connection.execute(
            "INSERT INTO devices (id, hostname, asset_id) VALUES (?, ?, ?)",
            (device_id, device_id, asset_id),
        )
        connection.commit()
        _persist_discovered_version(device_id, "7.1.070")
        _persist_discovered_version(device_id, "overwrite-attempt")
        assert connection.execute("SELECT version FROM devices WHERE id = ?", (device_id,)).fetchone()[0] == "7.1.070"
    finally:
        connection.close()


def test_version_migration_is_idempotent_on_legacy_postgresql_table(isolated_db):
    connection = get_db_connection()
    try:
        connection.execute("CREATE TEMP TABLE devices (id TEXT PRIMARY KEY)")
        upgrade(connection, True)
        upgrade(connection, True)
        connection.execute("INSERT INTO devices (id, version) VALUES (?, ?)", ("legacy", "1.0"))
        assert connection.execute("SELECT version FROM devices WHERE id = ?", ("legacy",)).fetchone()[0] == "1.0"
    finally:
        connection.close()


def test_exporter_enum_keys_are_numeric_without_changing_saved_config():
    config = {"get": ["1.3.6.1.2.1.1.1.0"], "metrics": [{
        "name": "enum_status", "oid": "1.3.6.1.2.1.1.1", "type": "EnumAsInfo",
        "enum_values": {"1": "online", "2": "offline"},
    }]}
    saved = _parse_variant_oid_config(config, include_unit=True)
    runtime = _parse_variant_oid_config(config, include_unit=False)
    assert saved["metrics"][0]["enum_values"] == {"1": "online", "2": "offline"}
    rendered = yaml.safe_load(yaml.safe_dump(runtime))
    assert rendered["metrics"][0]["enum_values"] == {1: "online", 2: "offline"}


@pytest.mark.parametrize("enum_values", [{"up": "online"}, {"1": "online", "+1": "duplicate"}, {"1": 1}])
def test_invalid_exporter_enums_fail_explicitly(enum_values):
    config = {"get": ["1.3.6.1.2.1.1.1.0"], "metrics": [{
        "name": "enum_status", "oid": "1.3.6.1.2.1.1.1", "type": "EnumAsInfo",
        "enum_values": enum_values,
    }]}
    with pytest.raises(CompileError):
        _parse_variant_oid_config(config, include_unit=False)
