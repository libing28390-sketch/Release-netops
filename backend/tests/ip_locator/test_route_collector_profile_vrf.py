from __future__ import annotations

from database import get_db_connection
from services import ip_locator_service


H3C_VRF_INVENTORY = """\
Total VPN-Instances configured : 2
VPN-Instance Name               RD                     Create time
VRF_A                           100:1                  2026/11/10 20:14:33
VRF_B                           200:1                  2026/11/10 20:14:33
"""


def test_profile_route_collector_persists_live_h3c_vrfs_in_isolated_store(
    isolated_db, monkeypatch,
):
    del isolated_db
    device = {
        "id": "fixture-h3c-s6850-vrf-collector",
        "hostname": "S6850_1",
        "ip_address": "192.0.2.10",
        "platform": "h3c_comware",
        "platform_profile_id": "system-profile-h3c_comware_v7",
        "tenant_id": "tenant-default",
        "role": "router",
        "status": "online",
    }
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices (id, hostname, status) VALUES (?, ?, 'online')",
            (device["id"], device["hostname"]),
        )
        conn.commit()

    def load_eligible_devices(**kwargs):
        diagnostics = kwargs.get("diagnostics")
        if diagnostics is not None:
            diagnostics.update({
                "inventory_total": 1,
                "not_online": 0,
                "unsupported_platform": 0,
                "no_credentials": 0,
                "role_filtered": 0,
            })
        return [device]

    monkeypatch.setattr(ip_locator_service, "_load_eligible_devices", load_eligible_devices)
    monkeypatch.setattr(
        ip_locator_service,
        "_select_route_devices",
        lambda devices, **_kwargs: (
            devices,
            {
                "credentialed_online": 1,
                "selected": 1,
                "role": 0,
                "explicit": 0,
                "interface_evidence": 0,
                "policy_disabled": 0,
                "policy_ignored": 0,
                "no_l3_evidence": 0,
            },
        ),
    )
    monkeypatch.setattr(ip_locator_service, "is_snmp_collection_enabled", lambda _device: False)

    discovery_calls: list[tuple[str, str, bool]] = []

    def send_read_only_command(_device, command, force_refresh=False):
        discovery_calls.append((str(_device["id"]), command, force_refresh))
        assert command == "display ip vpn-instance"
        return H3C_VRF_INVENTORY

    monkeypatch.setattr(ip_locator_service, "_send_command", send_read_only_command)

    action_calls: list[tuple[str, str, dict | None]] = []
    routes_by_vrf = {
        "default": {
            "network": "10.0.0.0",
            "prefix_length": "24",
            "protocol": "Direct",
            "distance": "0",
            "metric": "0",
            "nexthop_ip": "10.0.0.1",
            "nexthop_if": "Vlan-interface1",
        },
        "VRF_A": {
            "network": "192.168.10.0",
            "prefix_length": "24",
            "protocol": "Direct",
            "distance": "0",
            "metric": "0",
            "nexthop_ip": "192.168.10.1",
            "nexthop_if": "Vlan-interface10",
        },
        "VRF_B": {
            "network": "192.168.20.0",
            "prefix_length": "24",
            "protocol": "Direct",
            "distance": "0",
            "metric": "0",
            "nexthop_ip": "192.168.20.1",
            "nexthop_if": "Vlan-interface20",
        },
    }

    def execute_action(device_id, action_code, *, user, parameters=None):
        assert device_id == device["id"]
        assert user["username"] == "route-collector"
        if action_code == "get_route_table":
            vrf = "default"
            assert parameters is None
        else:
            assert action_code == "get_route_table_vrf"
            assert parameters is not None
            vrf = parameters["vrf"]
        action_calls.append((action_code, vrf, parameters))
        return {
            "success": True,
            "parse_status": "matched",
            "records": [routes_by_vrf[vrf]],
        }

    from services import platform_registry_service

    monkeypatch.setattr(platform_registry_service, "execute_platform_action", execute_action)

    ip_locator_service.run_route_collector(
        respect_collection_policy=False,
        device_ids={device["id"]},
    )

    assert discovery_calls == [
        (device["id"], "display ip vpn-instance", True),
    ]
    assert [(action, vrf) for action, vrf, _parameters in action_calls] == [
        ("get_route_table", "default"),
        ("get_route_table_vrf", "VRF_A"),
        ("get_route_table_vrf", "VRF_B"),
    ]

    with ip_locator_service.get_db_connection() as conn:
        rows = conn.execute(
            """SELECT vrf_name, prefix, mask, next_hop, protocol, interface, metric
                 FROM route_cache
                WHERE device_id = ?
                ORDER BY vrf_name""",
            (device["id"],),
        ).fetchall()
        route_table_rows = conn.execute(
            """SELECT vrf_name, destination, next_hop, outgoing_interface
                 FROM route_table
                WHERE device_id = ?
                ORDER BY vrf_name""",
            (device["id"],),
        ).fetchall()

    assert {
        (row["vrf_name"], row["prefix"], row["mask"], row["next_hop"], row["interface"])
        for row in rows
    } == {
        ("VRF_A", "192.168.10.0", "24", "192.168.10.1", "Vlan-interface10"),
        ("VRF_B", "192.168.20.0", "24", "192.168.20.1", "Vlan-interface20"),
        ("default", "10.0.0.0", "24", "10.0.0.1", "Vlan-interface1"),
    }
    assert len(route_table_rows) == 3
    assert {str(row["vrf_name"]) for row in route_table_rows} == {"default", "VRF_A", "VRF_B"}
    assert all(str(row["destination"]).endswith("/24") for row in route_table_rows)
