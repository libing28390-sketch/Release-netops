"""Expand stored interface profiles with Counter64 packet and EtherLike OIDs."""

from __future__ import annotations

import json


VERSION = 154
NAME = "interface_counter64_error_oids"


_DEFAULTS = {
    "if_hc_in_ucast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.7",
    "if_hc_in_multicast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.8",
    "if_hc_in_broadcast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.9",
    "if_hc_out_ucast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.11",
    "if_hc_out_multicast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.12",
    "if_hc_out_broadcast_pkts_oid": "1.3.6.1.2.1.31.1.1.1.13",
    "dot3_hc_fcs_errors_oid": "1.3.6.1.2.1.10.7.11.1.2",
    "dot3_hc_frame_too_long_oid": "1.3.6.1.2.1.10.7.11.1.4",
    "dot3_hc_internal_mac_rx_errors_oid": "1.3.6.1.2.1.10.7.11.1.5",
    "dot3_hc_symbol_errors_oid": "1.3.6.1.2.1.10.7.11.1.6",
    "dot3_fcs_errors_oid": "1.3.6.1.2.1.10.7.2.1.3",
}


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute("SELECT id, interface_config_json FROM snmp_metric_profiles")
    rows = cursor.fetchall()
    for row in rows:
        profile_id = str(row[0] or "")
        try:
            config = json.loads(row[1] or "{}")
        except (TypeError, ValueError):
            config = {}
        if not isinstance(config, dict) or not config:
            continue
        changed = False
        for key, value in _DEFAULTS.items():
            if key not in config or not str(config.get(key) or "").strip():
                config[key] = value
                changed = True
        if changed:
            cursor.execute(
                "UPDATE snmp_metric_profiles SET interface_config_json = ? WHERE id = ?",
                (json.dumps(config, ensure_ascii=False, sort_keys=True), profile_id),
            )


def downgrade(cursor, use_pg: bool) -> None:
    # JSON fields are additive; retaining them keeps a rollback compatible
    # with a collector that already knows the expanded contract.
    return None

