from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from api import ipam as ipam_api
from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_routing_context_service import create_device_routing_context
from services.ipam_service import create_address, create_subnet, list_ip_inventory, list_subnets


def _id(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}"


def _site(site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT (id) DO NOTHING""",
            (site_id, site_id.upper(), site_id),
        )
        conn.commit()


def _device(device_id: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, tenant_id, site_id, site)
               VALUES (?, ?, '192.0.2.200', 'cisco_ios', 'online', 'tenant-default', ?, ?)""",
            (device_id, device_id, site_id, site_id),
        )
        conn.commit()


def _space(name: str) -> dict:
    return create_address_space(
        name=_id(name), kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )


def _prefix(prefix: str, *, space_id: str, site_id: str, name: str) -> dict:
    return create_subnet(
        prefix=prefix, address_space_id=space_id, tenant_id="tenant-default",
        site_id=site_id, name=name,
    )


def _restricted_user(make_user, site_id: str) -> dict:
    row = make_user(_id("ipam-read-scope"), role="Viewer", tenant_id="tenant-default")
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'ip_address', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id("ipam-read-grant"), row["user_id"], site_id, json.dumps(["view"])),
        )
        conn.commit()
    return {
        "id": row["user_id"], "username": row["username"], "role": "Viewer",
        "tenant_id": "tenant-default", "scope_mode": "restricted",
    }


def _publish_arp(
    *, device_id: str, address: str, mac: str,
    context_type: str = "global", context_key: str = "Global",
    status: str = "complete",
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn, device_id=device_id, observation_source="arp", context_source="cli",
            context_type=context_type, local_context_key=context_key,
            attempted_at=now, run_id=_id("arp-run"),
        )
        conn.commit()
        finish_current_endpoint_collection(
            conn, device_id=device_id, observation_source="arp", context_source="cli",
            context_type=context_type, local_context_key=context_key,
            generation=generation, status=status, attempted_at=now, completed_at=now,
            observations=[{
                "ip_address": address, "mac_address": mac, "context_source": "cli",
                "context_type": context_type, "local_context_key": context_key,
                "observed_at": now,
            }],
            run_id=_id("arp-run"),
        )
        conn.commit()
    return now.isoformat()


def test_restricted_ip_detail_and_mac_enrichment_stay_in_site_and_address_space(
    isolated_db, make_user,
):
    del isolated_db
    site_a, site_b = _id("read-site-a"), _id("read-site-b")
    _site(site_a)
    _site(site_b)
    space_a, space_b = _space("Read Global A"), _space("Read Global B")
    prefix_a = _prefix("10.253.10.0/24", space_id=space_a["id"], site_id=site_a, name="A")
    prefix_b = _prefix("10.253.10.0/24", space_id=space_b["id"], site_id=site_b, name="B")
    device_a, device_b = _id("read-device-a"), _id("read-device-b")
    _device(device_a, site_a)
    _device(device_b, site_b)
    create_device_routing_context(
        device_id=device_a, context_source="cli", context_type="global",
        local_context_key="Global", address_space_id=space_a["id"],
        security_tenant_id="tenant-default",
    )
    create_device_routing_context(
        device_id=device_b, context_source="cli", context_type="global",
        local_context_key="Global", address_space_id=space_b["id"],
        security_tenant_id="tenant-default",
    )
    target = create_address(
        prefix_a["id"], address="10.253.10.50", device_id=device_a,
        interface_name="Loopback50", mac_address="",
    )
    other = create_address(prefix_b["id"], address="10.253.10.50")
    single_space = create_address(
        prefix_a["id"], address="10.253.10.53", device_id=device_a,
        interface_name="Loopback53", mac_address="",
    )
    foreign_device_address = create_address(
        prefix_a["id"], address="10.253.10.51", device_id=device_b,
        interface_name="Loopback51", interface_id="",
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, mac_address)
               VALUES (?, ?, 'Loopback50', ''), (?, ?, 'Loopback51', '00:bb:bb:bb:bb:51')""",
            (_id("read-intf-a"), device_a, _id("read-intf-b"), device_b),
        )
        conn.commit()

    # A mapped observation is authoritative only for space B, while an unknown
    # current context remains pending even though .53 has one registered scope.
    _publish_arp(device_id=device_b, address="10.253.10.50", mac="00:11:22:33:44:bb")
    _publish_arp(
        device_id=device_a, address="10.253.10.53", mac="00:11:22:33:44:53",
        context_type="unknown", context_key="unmapped", status="scope_unknown",
    )

    user = _restricted_user(make_user, site_a)
    detail = ipam_api.api_get_address_detail(target["id"], _user=user)
    assert detail["same_ip_elsewhere"] == []
    assert detail["discovery"] == []
    assert "interface_mac" not in detail["address"]
    assert "10.253.10.50" == detail["address"]["address"]

    list_result = ipam_api.api_list_ip_inventory(
        _user=user, page=1, page_size=100, registered_only=True,
    )
    by_id = {item["id"]: item for item in list_result["items"]}
    assert "interface_mac" not in by_id[target["id"]]
    assert "interface_liveness" not in by_id[foreign_device_address["id"]]
    assert "interface_mac" not in by_id[foreign_device_address["id"]]
    assert "interface_mac" not in by_id[single_space["id"]]

    unrestricted_detail = ipam_api.api_get_address_detail(target["id"], _user=None)
    other_row = next(item for item in unrestricted_detail["same_ip_elsewhere"] if item["id"] == other["id"])
    assert other_row["same_routing_domain"] is False

    prefixes = {item["id"]: item for item in list_subnets(page=None)}
    assert prefixes[prefix_a["id"]]["active_arp_ips"] == 0
    assert prefixes[prefix_b["id"]]["active_arp_ips"] == 1


def test_legacy_arp_mac_fallback_requires_known_context_and_unique_space(isolated_db):
    del isolated_db
    site = _id("legacy-read-site")
    _site(site)
    space = _space("Legacy Global")
    prefix = _prefix("10.253.20.0/24", space_id=space["id"], site_id=site, name="Legacy")
    device = _id("legacy-read-device")
    _device(device, site)
    address = create_address(
        prefix["id"], address="10.253.20.55", device_id=device,
        interface_name="Loopback55", mac_address="",
    )
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO network_endpoints
                   (id, ip, mac, hostname, switch_id, switch_port, vlan, vrf, site,
                    source_type, first_seen, last_seen, is_active)
               VALUES (?, '10.253.20.55', '00:11:22:33:44:55', 'legacy-host', ?, 'GE0/0/1',
                       '', 'Global', ?, 'arp', ?, ?, 1)""",
            (_id("legacy-endpoint"), device, site, observed_at, observed_at),
        )
        conn.commit()

    inventory = list_ip_inventory(registered_only=True, page=1, page_size=100)
    item = next(row for row in inventory["items"] if row["id"] == address["id"])
    assert item["interface_mac"] == "001122334455"
    assert item["interface_mac_source"] == "neighbor_arp"
    prefixes = {row["id"]: row for row in list_subnets(page=None)}
    assert prefixes[prefix["id"]]["active_arp_ips"] == 1


def test_detail_hides_foreign_bound_device_and_filters_historical_subnet_scope(
    isolated_db, make_user,
):
    del isolated_db
    site_a, site_b = _id("detail-site-a"), _id("detail-site-b")
    _site(site_a)
    _site(site_b)
    space_a, space_b = _space("Detail A"), _space("Detail B")
    prefix_a = _prefix("10.253.30.0/24", space_id=space_a["id"], site_id=site_a, name="Detail A")
    prefix_b = _prefix("10.253.31.0/24", space_id=space_b["id"], site_id=site_b, name="Detail B")
    device_b = _id("detail-device-b")
    _device(device_b, site_b)
    address = create_address(
        prefix_a["id"], address="10.253.30.10", device_id=device_b,
        interface_name="GigabitEthernet0/1", mac_address="",
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO interfaces
                   (id, device_id, interface_name, admin_status, oper_status, mac_address)
               VALUES (?, ?, 'GigabitEthernet0/1', 'up', 'up', '00:bb:bb:bb:bb:bb')""",
            (_id("detail-interface"), device_b),
        )
        conn.commit()
    from services.audit_service import log_audit_event
    log_audit_event(
        event_type="ipam.address.update", category="ipam", severity="info", status="success",
        summary="Moved address reference", target_type="ip_address", target_id=address["id"],
        before={"subnet_id": prefix_b["id"]}, after={"subnet_id": prefix_a["id"]},
    )

    user = _restricted_user(make_user, site_a)
    detail = ipam_api.api_get_address_detail(address["id"], _user=user)
    assert detail["address"]["device_id"] == ""
    assert detail["address"]["bound_device_hostname"] == ""
    assert detail["address"]["asset_serial_number"] == ""
    assert detail["address"]["asset_management_ip"] == ""
    assert detail["interface"] is None
    assert "interface_liveness" not in detail["address"]
    assert detail["history"] == []
