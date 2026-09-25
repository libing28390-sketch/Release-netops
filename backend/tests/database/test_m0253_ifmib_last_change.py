from __future__ import annotations

import hashlib
import json

from database import get_db_connection
from database.migrations.m0253_expand_ifmib_last_change import upgrade
from services.monitoring_oid_catalog import iter_builtin_catalog


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_m0253_preserves_operator_oid_edits_and_adds_if_last_change(isolated_db):
    item = next(
        entry for entry in iter_builtin_catalog()
        if entry.get("module_key") == "generic_ifmib_interface"
    )
    variant_id = item["variant"]["id"]
    operator_config = {
        "schema_version": "1",
        "mib_sources": ["OPERATOR-MIB"],
        "walk": ["1.3.6.1.4.1.9999"],
        "get": [],
        "metrics": [
            {"name": "ifName", "oid": "1.3.6.1.4.1.9999.1", "type": "DisplayString"},
            {"name": "operatorCustomGauge", "oid": "1.3.6.1.4.1.9999.2", "type": "gauge"},
        ],
    }

    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE snmp_module_variants
                  SET oid_config_json = ?, generator_config_hash = 'stale', mib_hash = 'stale'
                WHERE id = ?""",
            (_canonical_json(operator_config), variant_id),
        )
        conn.commit()

        upgrade(conn, use_pg=True)
        conn.commit()

        row = conn.execute(
            """SELECT oid_config_json, generator_config_hash, mib_hash
                 FROM snmp_module_variants WHERE id = ?""",
            (variant_id,),
        ).fetchone()
        updated = json.loads(row["oid_config_json"])
        metrics = updated["metrics"]
        assert updated["mib_sources"] == operator_config["mib_sources"]
        assert updated["walk"] == operator_config["walk"]
        assert next(metric for metric in metrics if metric["name"] == "ifName")["oid"] == "1.3.6.1.4.1.9999.1"
        assert any(metric["name"] == "operatorCustomGauge" for metric in metrics)
        assert sum(metric["name"] == "ifLastChange" for metric in metrics) == 1
        assert row["generator_config_hash"] == hashlib.sha256(_canonical_json(updated).encode("utf-8")).hexdigest()
        assert row["mib_hash"] == hashlib.sha256(_canonical_json(updated["mib_sources"]).encode("utf-8")).hexdigest()

        upgrade(conn, use_pg=True)
        conn.commit()
        repeated = conn.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        assert json.loads(repeated["oid_config_json"]) == updated

        conn.execute(
            "UPDATE snmp_module_variants SET oid_config_json = '{}' WHERE id = ?",
            (variant_id,),
        )
        conn.commit()
        upgrade(conn, use_pg=True)
        conn.commit()
        seeded = conn.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        assert json.loads(seeded["oid_config_json"]) == item["variant"]["oid_config"]
    finally:
        conn.close()
