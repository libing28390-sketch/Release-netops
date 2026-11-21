from __future__ import annotations

import json

import database
from database.migrations import m0236_expand_h3c_monitoring_oids as migration
from database.migrations import m0237_sync_h3c_oid_runtime_defaults as runtime_defaults
from database.migrations import m0238_sync_h3c_metric_types as metric_types


def _as_json(value):
    return json.loads(value) if isinstance(value, str) else value


def test_m0236_refreshes_h3c_oid_catalog_and_is_idempotent(isolated_db):
    connection = database.get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        h3c = connection.execute(
            "SELECT oid_config_json, supported_models FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_common_std",),
        ).fetchone()
        assert h3c
        config = _as_json(h3c[0])
        assert {
            "1.3.6.1.4.1.25506.2.6.1.2.1.1",
            "1.3.6.1.4.1.25506.2.5.1.1.4.1.1",
            "1.3.6.1.4.1.25506.8.35.9.1.1.1",
            "1.3.6.1.4.1.25506.8.35.9.1.2.1",
        } <= set(config["walk"])
        assert {"hh3cDevMFanStatus", "hh3cDevMPowerStatus", "hh3cFlhPartSpace", "hh3cEntityExtMacAddressCount"} <= {
            item["name"] for item in config["metrics"]
        }
        h3c_metric_oids = {item["oid"] for item in config["metrics"]}
        assert {
            "1.3.6.1.4.1.25506.2.6.1.1.1.1.11",
            "1.3.6.1.4.1.25506.2.6.1.1.1.1.19",
            "1.3.6.1.4.1.25506.8.35.9.1.1.1.2",
            "1.3.6.1.4.1.25506.8.35.9.1.2.1.2",
            "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.4",
            "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.5",
            "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.8",
            "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.10",
            "1.3.6.1.4.1.25506.8.35.5.1.12",
            "1.3.6.1.4.1.25506.2.6.1.2.1.1.5",
        } <= h3c_metric_oids
        assert "S5130" in set(_as_json(h3c[1]))

        generic = connection.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE variant_key = ?",
            ("generic_ifmib_interface_std",),
        ).fetchone()
        generic_config = _as_json(generic[0])
        assert {"ifHCInUcastPkts", "ifHCInMulticastPkts", "ifHCOutUcastPkts", "ifPhysAddress"} <= {
            item["name"] for item in generic_config["metrics"]
        }
    finally:
        connection.close()


def test_m0237_syncs_h3c_runtime_defaults(isolated_db):
    connection = database.get_db_connection()
    try:
        runtime_defaults.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        row = connection.execute(
            "SELECT retries, request_timeout_ms FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_common_std",),
        ).fetchone()
        assert tuple(row) == (3, 5000)
    finally:
        connection.close()


def test_m0238_keeps_h3c_status_metrics_enumerated(isolated_db):
    connection = database.get_db_connection()
    try:
        metric_types.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        config = _as_json(connection.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_common_std",),
        ).fetchone()[0])
        types = {item["name"]: item["type"] for item in config["metrics"]}
        assert types["hh3cEntityExtOperStatus"] == "EnumAsInfo"
        assert types["hh3cEntityExtErrorStatus"] == "EnumAsInfo"
    finally:
        connection.close()
