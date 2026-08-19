from __future__ import annotations

import json
import sqlite3

from database.migrations.m0154_interface_counter64_error_oids import upgrade


def test_m0154_backfills_new_interface_oids_without_overwriting_custom_values() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE snmp_metric_profiles (id TEXT PRIMARY KEY, interface_config_json TEXT)"
    )
    conn.execute(
        "INSERT INTO snmp_metric_profiles (id, interface_config_json) VALUES (?, ?)",
        (
            "h3c-s6800",
            json.dumps(
                {
                    "enabled": True,
                    "if_hc_in_ucast_pkts_oid": "1.3.6.1.4.1.25506.99.1",
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO snmp_metric_profiles (id, interface_config_json) VALUES (?, ?)",
        ("empty", "{}"),
    )

    upgrade(conn.cursor(), use_pg=False)
    upgrade(conn.cursor(), use_pg=False)

    config = json.loads(
        conn.execute(
            "SELECT interface_config_json FROM snmp_metric_profiles WHERE id = ?",
            ("h3c-s6800",),
        ).fetchone()[0]
    )
    assert config["if_hc_in_ucast_pkts_oid"] == "1.3.6.1.4.1.25506.99.1"
    assert config["if_hc_out_broadcast_pkts_oid"] == "1.3.6.1.2.1.31.1.1.1.13"
    assert config["dot3_hc_fcs_errors_oid"] == "1.3.6.1.2.1.10.7.11.1.2"

    empty_config = conn.execute(
        "SELECT interface_config_json FROM snmp_metric_profiles WHERE id = ?",
        ("empty",),
    ).fetchone()[0]
    assert empty_config == "{}"
