from pathlib import Path
import ipaddress

import services.ip_locator_service as ip_locator_service


DEVICE = {
    "id": "device-1",
    "hostname": "sw-01",
    "ip_address": "192.0.2.10",
}


def test_locator_normalizes_huawei_ge_and_gigabitethernet_as_the_same_port():
    assert ip_locator_service.normalize_interface_name("GE0/0/4") == "gi0/0/4"
    assert ip_locator_service.normalize_interface_name("GigabitEthernet0/0/4") == "gi0/0/4"


def test_route_selection_prefers_prefix_bound_connected_gateway_over_ospf():
    rows = [
        {
            "device_id": "lsw2",
            "destination": "10.253.20.0/24",
            "next_hop": "10.253.1.10",
            "protocol": "ospf",
            "outgoing_interface": "Vlanif23",
            "last_updated": "2026-08-05T21:21:22+00:00",
        },
        {
            "device_id": "lsw5",
            "destination": "10.253.20.0/24",
            "next_hop": "directly connected",
            "protocol": "connected",
            "outgoing_interface": "Vlanif20",
            "last_updated": "2026-08-05T21:20:00+00:00",
        },
    ]

    selected = ip_locator_service._select_best_route(
        rows,
        ipaddress.ip_address("10.253.20.10"),
        gateway_device_id="lsw5",
    )

    assert selected["device_id"] == "lsw5"
    assert selected["protocol"] == "connected"
    assert selected["outgoing_interface"] == "Vlanif20"


def test_realtime_arp_lookup_uses_capability_rules_and_never_builds_zero_workers(monkeypatch):
    devices = [
        {"id": "router-1", "role": "router", "ip_address": "192.0.2.1"},
        {"id": "access-1", "role": "access", "ip_address": "192.0.2.2"},
        {
            "id": "disabled-1",
            "role": "core",
            "ip_address": "192.0.2.3",
            "collection_policy_json": '{"collectors":{"arp":false}}',
        },
    ]
    monkeypatch.setattr(ip_locator_service, "_load_svi_evidence", lambda: {"access-1"})

    selected = ip_locator_service._load_realtime_arp_devices(devices)

    assert [device["id"] for device in selected] == ["access-1", "router-1"]
    assert all(device["_arp_policy_override"] is True for device in selected)
    assert ip_locator_service._calc_ssh_workers(0) == 1


def test_locator_context_falls_back_to_latest_interface_telemetry(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-locator-switch", "LSW4", "online", "", ""),
    )
    conn.execute(
        """INSERT INTO network_endpoints
           (id, ip, mac, hostname, switch_id, switch_port, vlan, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "endpoint-locator-1", "10.253.10.10", "5489985666e2", "endpoint-1",
            "device-locator-switch", "GE0/0/4", "10", "2026-08-02T21:50:00+08:00", "2026-08-02T21:54:00+08:00",
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, admin_status, oper_status, switchport_mode, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "interface-locator-1", "device-locator-switch", "GigabitEthernet0/0/4",
            "unknown", "unknown", "access", "2026-08-02T21:54:00+00:00",
        ),
    )
    conn.execute(
        """INSERT INTO interface_telemetry_raw
           (ts, device_id, interface_name, status)
           VALUES (?, ?, ?, ?)""",
        ("2026-08-02T21:55:00+00:00", "device-locator-switch", "GE0/0/4", "up"),
    )
    conn.commit()

    context = ip_locator_service._get_ip_locator_context("10.253.10.10")

    assert context["l2"]["switch_name"] == "LSW4"
    assert context["l2"]["admin_status"] == "up"
    assert context["l2"]["oper_status"] == "up"
    assert context["l2"]["mode"] == "access"
    assert context["address"]["status"] == "active"
    assert context["freshness"]["interface_last_seen"] == "2026-08-02T21:55:00+00:00"
    conn.close()


def test_locator_uses_lldp_uplink_when_gateway_is_on_the_access_switch(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-access-gw", "S6850-5", "online", "access"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-distribution", "S6850-3", "online", "distribution"),
    )
    conn.execute(
        """INSERT INTO prefixes
           (id, prefix, gateway, status, gateway_device_id)
           VALUES (?, ?, ?, ?, ?)""",
        ("prefix-locator-uplink", "172.16.5.0/24", "172.16.5.1", "active", "device-access-gw"),
    )
    conn.execute(
        """INSERT INTO network_endpoints
           (id, ip, mac, hostname, switch_id, switch_port, vlan, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "endpoint-locator-uplink", "172.16.5.10", "8e4757600706", "endpoint-1",
            "device-access-gw", "GE1/0/2", "7", "2026-08-05T21:50:00+08:00", "2026-08-05T21:54:00+08:00",
        ),
    )
    conn.execute(
        """INSERT INTO topology_links
           (id, source_device_id, source_hostname, source_port,
            target_device_id, target_hostname, target_port, status, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "link-locator-uplink", "device-distribution", "S6850-3", "Ten-GigabitEthernet1/0/49",
            "device-access-gw", "S6850-5", "Ten-GigabitEthernet1/0/49", "unknown", "2026-08-05T21:55:00+00:00",
        ),
    )
    conn.commit()

    context = ip_locator_service._get_ip_locator_context("172.16.5.10")

    assert context["l3"]["gateway_device"] == "S6850-5"
    assert context["l3"]["upstream_devices"] == [{
        "device": "S6850-3",
        "device_id": "device-distribution",
        "port": "Ten-GigabitEthernet1/0/49",
        "peer_port": "Ten-GigabitEthernet1/0/49",
    }]
    conn.close()


def test_locator_lldp_lookup_overrides_background_plan_for_interactive_trace(monkeypatch):
    calls = {}

    def fake_collect(_device, *, categories, policy_override_categories=None):
        calls["categories"] = categories
        calls["policy_override_categories"] = policy_override_categories
        return {
            "categories": [{
                "key": "neighbors",
                "success": True,
                "records": [{
                    "local_interface": "XGE1/0/49",
                    "neighbor_name": "S6850-3",
                    "neighbor_interface": "Ten-GigabitEthernet1/0/49",
                }],
            }],
        }

    monkeypatch.setattr(ip_locator_service, "collect_operational_data", fake_collect)

    assert ip_locator_service._collect_lldp_from_device({
        "id": "device-access-gw",
        "hostname": "S6850-5",
        "platform": "hp_comware",
    }) == [{
        "local_interface": "XGE1/0/49",
        "neighbor": "S6850-3",
        "neighbor_port": "Ten-GigabitEthernet1/0/49",
    }]
    assert calls == {
        "categories": ["neighbors"],
        "policy_override_categories": {"neighbors"},
    }


def test_locator_live_status_enrichment_reads_only_the_target_access_port(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "_load_eligible_devices",
        lambda: [{"id": "device-locator-switch", "hostname": "LSW4", "platform": "huawei_vrp"}],
    )
    monkeypatch.setattr(
        "services.read_only_collection_adapter.collect_read_only_evidence",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "interfaces",
                "success": True,
                "parse_status": "matched",
                "records": [{
                    "INTERFACE": "GigabitEthernet0/0/4",
                    "PHY": "up",
                    "PROTOCOL": "up",
                }],
            }],
        },
    )

    assert ip_locator_service._collect_live_interface_status(
        "device-locator-switch", "GE0/0/4"
    ) == ("up", "up")


def test_normalize_arp_record_accepts_textfsm_standard_fields():
    record = ip_locator_service._normalize_arp_record(
        {
            "IP_ADDRESS": "10.1.1.1",
            "MAC_ADDRESS": "02e0-f102-0023",
            "INTERFACE": "GE1/0/1",
        },
        DEVICE,
    )

    assert record == {
        "ip": "10.1.1.1",
        "mac": "02e0f1020023",
        "interface": "GE1/0/1",
        "source_device_id": "device-1",
        "source_device": "sw-01",
    }


def test_targeted_arp_query_uses_published_registry_action_for_bound_device(monkeypatch):
    device = {**DEVICE, "platform_profile_id": "system-profile-cisco_ios", "tenant_id": "tenant-1"}
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{
                "IP_ADDRESS": "10.1.1.1",
                "MAC_ADDRESS": "02e0-f102-0023",
                "INTERFACE": "Gi1/0/1",
            }],
        },
    )

    result = ip_locator_service._targeted_arp_query(device, "10.1.1.1")

    assert result["mac"] == "02e0f1020023"
    assert result["interface"] == "Gi1/0/1"


def test_targeted_mac_query_uses_published_registry_action_for_bound_device(monkeypatch):
    device = {
        **DEVICE,
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{
                "MAC_ADDRESS": "02e0-f102-0023",
                "VLAN_ID": "12",
                "DESTINATION_PORT": "Gi1/0/1",
            }],
        },
    )

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == [{
        "mac": "02e0f1020023",
        "port": "Gi1/0/1",
        "vlan": "12",
        "vlan_source": "mac_table",
        "type": "",
        "switch_id": "device-1",
        "switch_name": "sw-01",
    }]


def test_targeted_mac_query_skips_router_without_overriding_collection_plan(monkeypatch):
    device = {
        **DEVICE,
        "role": "router",
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
    }
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("router MAC lookup must be skipped")

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", fail_if_called)

    assert ip_locator_service._targeted_mac_query(device, "02e0f1020023") == []


def test_targeted_mac_query_allows_explicit_router_collection_override(monkeypatch):
    device = {
        **DEVICE,
        "role": "router",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{"MAC_ADDRESS": "02e0-f102-0023", "VLAN_ID": "12", "DESTINATION_PORT": "Gi1/0/1"}],
        },
    )

    assert ip_locator_service._targeted_mac_query(device, "02e0f1020023")[0]["vlan"] == "12"


def test_format_mac_uses_platform_hyphen_style():
    assert ip_locator_service._format_mac("548998106981") == "5489-9810-6981"


def test_full_mac_collection_parses_huawei_vrp_mac_table_layout(monkeypatch):
    output = """
MAC address table of slot 0:
4c1f-cc3c-7de1 20          -      -      GE0/0/4         dynamic   0/-
Total matching items on slot 0 displayed = 1
"""
    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *_args: output)

    records = ip_locator_service._collect_full_mac_table_from_device({
        **DEVICE,
        "platform": "huawei_vrp",
    })

    assert records == [{
        "mac": "4c1fcc3c7de1",
        "vlan": "20",
        "port": "GE0/0/4",
        "type": "dynamic",
        "switch_id": "device-1",
        "switch_name": "sw-01",
    }]


def test_endpoint_mac_records_are_persisted_for_cmdb_and_offline_lookup(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, status) VALUES (?, ?, ?)",
            ("device-mac-1", "sw-mac-01", "online"),
        )
        conn.commit()
    finally:
        conn.close()

    persisted = ip_locator_service._persist_mac_table_records([{
        "switch_id": "device-mac-1",
        "mac": "4c1f-cc3c-7de1",
        "vlan": "20",
        "port": "GE0/0/4",
        "type": "dynamic",
    }])

    conn = isolated_db["module"].get_db_connection()
    try:
        row = conn.execute(
            "SELECT mac_address, vlan_id, interface_name, entry_type FROM mac_table WHERE device_id = ?",
            ("device-mac-1",),
        ).fetchone()
    finally:
        conn.close()

    assert persisted == 1
    assert dict(row) == {
        "mac_address": "4c1fcc3c7de1",
        "vlan_id": 20,
        "interface_name": "GE0/0/4",
        "entry_type": "dynamic",
    }


def test_arp_output_fallback_accepts_common_cisco_and_huawei_mac_formats():
    output = """
Internet 10.1.1.2 0 aabb.ccdd.eeff ARPA GigabitEthernet1/0/2
10.1.1.3 00e0-fc41-0200  D  GE1/0/3
"""

    records = ip_locator_service._parse_arp_output_fallback(output, DEVICE)

    assert [(item["ip"], item["mac"], item["interface"]) for item in records] == [
        ("10.1.1.2", "aabbccddeeff", "GigabitEthernet1/0/2"),
        ("10.1.1.3", "00e0fc410200", "GE1/0/3"),
    ]


def test_arp_output_fallback_extracts_h3c_vid():
    records = ip_locator_service._parse_arp_output_fallback(
        "10.1.1.2 00e0-fc00-0001 12 GE1/0/2 960 D",
        DEVICE,
    )

    assert records[0]["vlan"] == "12"


def test_huawei_arp_continuation_line_is_attached_to_previous_entry():
    output = """
IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE INTERFACE      VPN-INSTANCE
                                          VLAN
------------------------------------------------------------------------------
10.253.20.2     4c1f-ccad-6fd7            I -  Vlanif20
10.253.20.1     4c1f-cc3c-7de1  5         D-0  GE0/0/4
                                          20
10.253.20.10    5489-9810-6981  20        D-0  GE0/0/1
                                          20
------------------------------------------------------------------------------
Total:3         Dynamic:2       Static:0     Interface:1
"""

    records = ip_locator_service._parse_arp_output_fallback(output, DEVICE)

    assert {item["ip"]: item.get("vlan") for item in records} == {
        "10.253.20.2": "20",
        "10.253.20.1": "20",
        "10.253.20.10": "20",
    }


def test_full_arp_collection_uses_normalized_records_and_raw_fallback(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["show arp"],
                    "parser": "ntc-templates",
                    "records": [
                        {
                            "IP_ADDRESS": "10.1.1.10",
                            "MAC_ADDRESS": "aabb.ccdd.0010",
                            "INTERFACE": "Gi1/0/10",
                        }
                    ],
                    "raw_outputs": [],
                }
            ]
        },
    )
    parsed = ip_locator_service._collect_full_arp_from_device(DEVICE)
    assert parsed[0]["ip"] == "10.1.1.10"
    assert parsed[0]["mac"] == "aabbccdd0010"

    fixture = Path(
        "backend/tests/fixtures/cli/h3c/h3c_comware/display_arp_all/comware_v7_s5130.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["display arp all"],
                    "parser": "ntc-templates",
                    "records": [],
                    "raw_outputs": [{"output": fixture}],
                }
            ]
        },
    )
    assert len(ip_locator_service._collect_full_arp_from_device(DEVICE)) == 2


def test_arp_failure_is_classified_and_backed_off():
    assert ip_locator_service._classify_arp_failure("SSH connection timed out") == "unreachable"
    assert ip_locator_service._classify_arp_failure("Authentication failed") == "auth_failed"
    assert ip_locator_service._arp_retry_delay("unreachable", 1) == 300
    assert ip_locator_service._arp_retry_delay("unreachable", 5) == 3600
    assert ip_locator_service._arp_retry_delay("auth_failed", 1) == 3600
    assert ip_locator_service._arp_retry_delay("unsupported", 1) == 86400


def test_full_arp_collection_returns_failure_metadata(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": False,
                    "error": "SSH connection timed out",
                    "records": [],
                    "raw_outputs": [],
                }
            ]
        },
    )

    result = ip_locator_service._collect_full_arp_result(DEVICE)
    assert result["status"] == "failed"
    assert result["failure_class"] == "unreachable"
    assert result["entries"] == []


def test_arp_sweep_reports_skipped_backoff_and_does_not_abort(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_sweep_devices",
        lambda *_args: ([DEVICE], 3, 2),
    )
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_collection_state",
        lambda: {"device-1": {"consecutive_failures": 0}},
    )
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_full_arp_result",
        lambda *_args, **_kwargs: {
            "entries": [],
            "status": "failed",
            "failure_class": "unreachable",
            "error_message": "SSH connection timed out",
        },
    )
    monkeypatch.setattr(ip_locator_service, "record_collection_results", lambda *_args, **_kwargs: None)

    result = ip_locator_service.run_arp_sweep()
    assert result["total_eligible_devices"] == 3
    assert result["skipped_backoff_devices"] == 2
    assert result["device_results"][0]["status"] == "failed"


def test_arp_sweep_device_selection_uses_bounded_cursor_batch(monkeypatch):
    devices = [
        {"id": f"device-{index}", "role": "router", "ip_address": f"10.0.0.{index}"}
        for index in range(5)
    ]
    monkeypatch.setattr(ip_locator_service, "_load_eligible_devices", lambda: devices)
    monkeypatch.setattr(ip_locator_service, "_load_svi_evidence", lambda: set())
    monkeypatch.setattr(ip_locator_service, "_load_arp_collection_state", lambda: {})
    monkeypatch.setattr(ip_locator_service, "ARP_MAX_DEVICES_PER_SWEEP", 2)
    monkeypatch.setattr(
        ip_locator_service,
        "reserve_collector_sweep_batch",
        lambda *_args, **_kwargs: {"start_cursor": 3, "selected_count": 2},
    )

    selected, total, skipped = ip_locator_service._load_arp_sweep_devices("run-1")

    assert [item["id"] for item in selected] == ["device-3", "device-4"]
    assert all(item["_arp_policy_override"] is True for item in selected)
    assert total == 5
    assert skipped == 0


def test_arp_dispatch_queues_only_device_ids_and_policy_metadata(monkeypatch):
    device = {"id": "device-1", "_arp_policy_override": True}
    captured = {}
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_sweep_devices",
        lambda *_args: ([device], 2, 1),
    )

    def enqueue(*_args, **kwargs):
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(ip_locator_service, "enqueue_tasks", enqueue)
    result = ip_locator_service.dispatch_arp_sweep()

    assert result["queued_devices"] == 1
    assert captured["device_ids"] == ["device-1"]
    assert captured["payload_by_device"]["device-1"]["arp_policy_override"] is True
