from __future__ import annotations

import json

import database
from database.migrations import m0273_complete_huawei_wireless_catalog as migration


def test_m0273_adds_huawei_radio_vap_metrics_and_repairs_mac_index_types(isolated_db):
    connection = database.get_db_connection()
    try:
        row = connection.execute(
            "SELECT id, oid_config_json FROM snmp_module_variants WHERE variant_key = ?",
            ("huawei_wireless_std",),
        ).fetchone()
        assert row is not None
        variant_id = row[0]
        config = json.loads(row[1])
        config["local_review_note"] = "preserve-me"
        config["metrics"] = [
            metric for metric in config.get("metrics", [])
            if metric.get("name") in {"hwWlanApMemoryUseRate", "hwWlanApCpuUseRate"}
        ]
        for metric in config["metrics"]:
            metric["indexes"] = [{"labelname": "ap_mac", "type": "gauge"}]
        config["walk"] = [
            oid for oid in config.get("walk", [])
            if oid not in {
                "1.3.6.1.4.1.2011.6.139.16.1.2.1.25",
                "1.3.6.1.4.1.2011.6.139.17.1.1.1.9",
            }
        ]
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
        serialized = upgraded[0]
        upgraded_config = json.loads(serialized)

        assert "HUAWEI-WLAN-AP-RADIO-MIB" in upgraded_config["mib_sources"]
        assert "1.3.6.1.4.1.2011.6.139.16.1.2.1.25" in upgraded_config["walk"]
        assert "1.3.6.1.4.1.2011.6.139.17.1.1.1.9" in upgraded_config["walk"]
        metrics = {metric["name"]: metric for metric in upgraded_config["metrics"]}
        for name in (
            "hwWlanRadioType", "hwWlanRadioWorkingChannel", "hwWlanRadioMac",
            "hwWlanRadioChUtilizationRate", "hwWlanRadioChInterferenceRate",
            "hwWlanRadioActualEIRP", "hwWlanVapStaOnlineCnt",
            "hwWlanSsid2gStaCnt", "hwWlanSsid5gStaCnt",
        ):
            assert name in metrics
        assert metrics["hwWlanApMemoryUseRate"]["indexes"] == [
            {"labelname": "ap_mac", "type": "PhysAddress48"},
        ]
        assert metrics["hwWlanRadioChUtilizationRate"]["indexes"] == [
            {"labelname": "ap_mac", "type": "PhysAddress48"},
            {"labelname": "radio_id", "type": "gauge"},
        ]
        assert metrics["hwWlanVapStaOnlineCnt"]["indexes"] == [
            {"labelname": "ap_mac", "type": "PhysAddress48"},
            {"labelname": "radio_index", "type": "gauge"},
            {"labelname": "wlan_id", "type": "gauge"},
        ]
        assert upgraded_config["local_review_note"] == "preserve-me"

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        repeated = connection.execute(
            "SELECT oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        assert repeated[0] == serialized
    finally:
        connection.close()
