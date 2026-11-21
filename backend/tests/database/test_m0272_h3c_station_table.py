from __future__ import annotations

import json

import database
from database.migrations import m0272_add_h3c_station_table as migration


def test_m0272_adds_verified_h3c_station_coverage_without_replacing_local_config(isolated_db):
    connection = database.get_db_connection()
    try:
        row = connection.execute(
            "SELECT id, oid_config_json FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_wireless_std",),
        ).fetchone()
        assert row is not None
        variant_id = row[0]
        config = json.loads(row[1])
        config["mib_sources"] = [
            item for item in config.get("mib_sources", [])
            if item != "HH3C-DOT11-STATION-MIB"
        ]
        config["source_urls"] = [
            item for item in config.get("source_urls", [])
            if item != "https://www.h3c.com/en/d_202604/2834085_294551_0.htm"
        ]
        config["walk"] = [
            item for item in config.get("walk", [])
            if item != "1.3.6.1.4.1.25506.2.75.3.1.1.1"
        ]
        config["local_review_note"] = "preserve-me"
        connection.execute(
            "UPDATE snmp_module_variants SET oid_config_json = ? WHERE id = ?",
            (json.dumps(config, ensure_ascii=False), variant_id),
        )
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgraded = connection.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        upgraded_config = json.loads(upgraded[0])
        assert "HH3C-DOT11-STATION-MIB" in upgraded_config["mib_sources"]
        assert "https://www.h3c.com/en/d_202604/2834085_294551_0.htm" in upgraded_config["source_urls"]
        assert "1.3.6.1.4.1.25506.2.75.3.1.1.1" in upgraded_config["walk"]
        assert upgraded_config["local_review_note"] == "preserve-me"

        serialized = upgraded[0]
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        repeated = connection.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        assert repeated[0] == serialized
    finally:
        connection.close()
