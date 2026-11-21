from __future__ import annotations

import json

import database
from database.migrations.m0254_append_optical_oid_metrics import upgrade


def test_optical_catalog_migration_appends_verified_metrics_without_overwriting_operator_config(isolated_db) -> None:
    conn = database.get_db_connection()
    try:
        row = conn.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            ("variant-h3c-common-std",),
        ).fetchone()
        assert row is not None
        config = json.loads(row[0] or "{}")
        operator_metric = {
            "name": "operatorOpticalNote",
            "oid": "1.3.6.1.4.1.99999.1",
            "type": "gauge",
            "help": "Operator-defined metric.",
        }
        config.setdefault("metrics", []).append(operator_metric)
        conn.execute(
            "UPDATE snmp_module_variants SET oid_config_json = ? WHERE id = ?",
            (json.dumps(config, ensure_ascii=False), "variant-h3c-common-std"),
        )
        conn.commit()

        upgrade(conn, use_pg=True)
        upgraded = json.loads(
            conn.execute(
                "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
                ("variant-h3c-common-std",),
            ).fetchone()[0]
        )
        names = {metric["name"] for metric in upgraded["metrics"]}
        assert "operatorOpticalNote" in names
        assert "hh3cTransceiverCurRXPowerDbm" in names
        assert "hh3cTransceiverCurTXPowerDbm" in names
        assert "1.3.6.1.4.1.25506.2.70.1.1.1" in upgraded["walk"]

        metric_count = len(upgraded["metrics"])
        walk_count = len(upgraded["walk"])
        upgrade(conn, use_pg=True)
        rerun = json.loads(
            conn.execute(
                "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
                ("variant-h3c-common-std",),
            ).fetchone()[0]
        )
        assert len(rerun["metrics"]) == metric_count
        assert len(rerun["walk"]) == walk_count
    finally:
        conn.close()
