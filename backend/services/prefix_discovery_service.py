"""Discover and classify IP prefixes from read-only device evidence."""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.interface_utils import normalize_interface_name
from services.read_only_collection_adapter import collect_read_only_evidence


CLASSIFICATION_RULE_VERSION = "prefix-classification-v1"
ALLOWED_NETWORK_TYPES = frozenset({
    "management", "transit", "loopback", "user_access", "network_service",
    "wan", "vpn", "vip", "unclassified",
})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)


def _first(record: dict[str, Any], *keys: str) -> str:
    folded = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = folded.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _interface_network(record: dict[str, Any]) -> tuple[str, str] | None:
    address = _first(record, "ip_address", "primary_ip", "main_ip", "ip", "address", "ipv4_address", "ipv6_address")
    prefix_value = _first(record, "prefix", "network", "cidr", "subnet")
    mask = _first(record, "netmask", "mask", "prefix_length", "prefixlen")
    raw = prefix_value if "/" in prefix_value else address
    if "/" not in raw and mask:
        raw = f"{raw}/{mask}"
    if "/" not in raw or not raw:
        return None
    try:
        interface = ipaddress.ip_interface(raw)
    except ValueError:
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            return None
        return str(network), str(network.version)
    network = interface.network
    return str(network), str(network.version)


def _loopback_host_network(record: dict[str, Any], interface: str) -> str | None:
    """Infer the host route only for an explicitly named loopback interface."""
    name = str(interface or '').strip().lower()
    if not (name.startswith('loopback') or name.startswith('lo')):
        return None
    address = _first(record, "ip_address", "primary_ip", "main_ip", "ip", "address", "ipv4_address", "ipv6_address")
    if not address or '/' in address:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    return f"{ip}/{32 if ip.version == 4 else 128}"


def _route_network(record: dict[str, Any]) -> tuple[str, str] | None:
    route_type = _first(record, "protocol", "route_type", "type", "code").lower()
    if route_type and not any(token in route_type for token in ("connected", "direct", "local", "interface")):
        return None
    raw = _first(record, "prefix", "network", "destination", "route", "cidr")
    if "/" not in raw:
        return None
    try:
        network = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        return None
    return str(network), str(network.version)


def _record_vlan(record: dict[str, Any], interface: str = "") -> str:
    value = _first(record, "vlan_id", "vlan", "vlanid", "outer_vlan", "vlan_tag")
    if value:
        match = re.search(r"\d+", value)
        if match:
            return match.group(0)
    match = re.search(r"(?:vlan|irb|bvi)[-_]?(\d+)", str(interface or ""), re.IGNORECASE)
    return match.group(1) if match else ""


def _record_ip(record: dict[str, Any]) -> str:
    return _first(record, "ip_address", "address", "ip", "ipv4_address", "ipv6_address").split("/", 1)[0]


def _classify_candidate(candidate: dict[str, Any]) -> tuple[str, float, list[str]]:
    evidence = candidate.get("evidence") or []
    interfaces = [str(item.get("interface") or "").lower() for item in evidence]
    names = " ".join(interfaces)
    reasons: list[str] = []
    if any(token in names for token in ("dns", "ntp", "radius", "tacacs", "wlc", "wireless", "ztp")):
        return "network_service", 0.86, ["network_service_interface"]
    if any(token in names for token in ("tunnel", "vpn", "vti", "gre", "ipsec")):
        return "vpn", 0.9, ["vpn_or_tunnel_interface"]
    if any(token in names for token in ("wan", "mpls", "cellular", "serial")):
        return "wan", 0.86, ["wan_interface"]
    if any("loopback" in item or item.startswith("lo") for item in interfaces):
        return "loopback", 0.98, ["loopback_interface"]
    prefix = ipaddress.ip_network(candidate["prefix"], strict=False)
    if (prefix.version == 4 and prefix.prefixlen in (30, 31)) or (prefix.version == 6 and prefix.prefixlen == 127):
        if any(item.get("neighbor") for item in evidence):
            return "transit", 0.95, ["point_to_point_prefix", "lldp_neighbor"]
        reasons.append("point_to_point_prefix_without_neighbor")
    if any(token in names for token in ("management", "mgmt", "oob", "me0", "mgt")):
        return "management", 0.92, ["management_interface"]
    if any(item.startswith("vlan") or item.startswith("irb") or item.startswith("bvi") for item in interfaces):
        return "user_access", 0.78, ["svi_or_irb_interface"]
    return "unclassified", 0.25, reasons or ["insufficient_evidence"]


def _interface_role_hint(interface: str) -> str:
    name = str(interface or '').lower()
    if any(token in name for token in ('loopback', 'lo')):
        return 'loopback'
    if any(token in name for token in ('management', 'mgmt', 'oob', 'me0', 'mgt')):
        return 'management'
    if any(token in name for token in ('tunnel', 'vpn', 'vti', 'gre', 'ipsec')):
        return 'vpn'
    if any(token in name for token in ('wan', 'mpls', 'cellular', 'serial')):
        return 'wan'
    if any(token in name for token in ('vlan', 'irb', 'bvi')):
        return 'user_access'
    if any(token in name for token in ('dns', 'ntp', 'radius', 'tacacs', 'wlc', 'wireless', 'ztp')):
        return 'network_service'
    return ''


def build_prefix_candidates(
    payload: dict[str, Any],
    *,
    tenant_id: str = "tenant-default",
    site_id: str = "",
    vrf_id: str = "",
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    device = payload.get("device") or {}
    device_id = str(device.get("id") or "")
    hostname = str(device.get("hostname") or device_id)
    category_map = {str(item.get("key")): item for item in payload.get("categories") or []}

    def add(raw_record: dict[str, Any], prefix: str, source_type: str, interface: str = "") -> None:
        network = ipaddress.ip_network(prefix, strict=False)
        key = (tenant_id, site_id, vrf_id, str(network.version), str(network))
        item = grouped.setdefault(key, {
            "candidate_id": f"candidate-{uuid.uuid4().hex[:12]}",
            "tenant_id": tenant_id, "site_id": site_id, "vrf_id": vrf_id,
            "prefix": str(network), "ip_version": network.version, "prefix_len": network.prefixlen,
            "evidence": [], "observed_devices": set(), "observed_interfaces": set(),
            "observed_vlans": set(), "observed_vrfs": set(),
        })
        item["observed_devices"].add(device_id)
        if interface:
            item["observed_interfaces"].add(interface)
        vlan = _record_vlan(raw_record, interface)
        if vlan:
            item["observed_vlans"].add(vlan)
        vrf = _first(raw_record, "vrf", "vrf_name", "routing_instance", "virtual_router")
        if vrf:
            item["observed_vrfs"].add(vrf)
        item["evidence"].append({
            "source_type": source_type,
            "device_id": device_id,
            "hostname": hostname,
            "interface": interface,
            "neighbor": _first(raw_record, "neighbor_name", "neighbor", "system_name"),
            "raw": raw_record,
        })

    for record in category_map.get("interfaces", {}).get("records") or []:
        if not isinstance(record, dict):
            continue
        interface = _first(record, "interface", "local_interface", "ifname", "name")
        parsed = _interface_network(record)
        if parsed:
            add(record, parsed[0], "interface", interface)
            continue
        inferred_loopback = _loopback_host_network(record, interface)
        if inferred_loopback:
            add(record, inferred_loopback, "interface_loopback_host", interface)
    for record in category_map.get("routing_table", {}).get("records") or []:
        if not isinstance(record, dict):
            continue
        parsed = _route_network(record)
        if parsed:
            add(record, parsed[0], "connected_route", _first(record, "interface", "outgoing_interface", "next_hop_interface"))

    neighbors = category_map.get("neighbors", {}).get("records") or []
    for item in grouped.values():
        for evidence in item["evidence"]:
            if evidence["source_type"] != "interface":
                continue
            local_interface = evidence.get("interface") or ""
            if any(_first(record, "local_interface", "interface", "local_port") == local_interface for record in neighbors if isinstance(record, dict)):
                evidence["neighbor"] = "lldp"

    def attach_supplemental_evidence(item: dict[str, Any], record: dict[str, Any], source_type: str, interface: str = "") -> None:
        item["evidence"].append({
            "source_type": source_type,
            "device_id": device_id,
            "hostname": hostname,
            "interface": interface,
            "neighbor": "",
            "raw": record,
        })
        vlan = _record_vlan(record, interface)
        if vlan:
            item["observed_vlans"].add(vlan)
        vrf = _first(record, "vrf", "vrf_name", "routing_instance", "virtual_router")
        if vrf:
            item["observed_vrfs"].add(vrf)

    for record in category_map.get("arp", {}).get("records") or []:
        if not isinstance(record, dict):
            continue
        try:
            address = ipaddress.ip_address(_record_ip(record))
        except ValueError:
            continue
        for item in grouped.values():
            if address in ipaddress.ip_network(item["prefix"], strict=False):
                attach_supplemental_evidence(
                    item, record, "arp", _first(record, "interface", "interface_name", "local_interface")
                )

    for record in category_map.get("mac_table", {}).get("records") or []:
        if not isinstance(record, dict):
            continue
        vlan = _record_vlan(record)
        if not vlan:
            continue
        for item in grouped.values():
            if vlan in item["observed_vlans"]:
                attach_supplemental_evidence(
                    item, record, "mac_table", _first(record, "interface", "interface_name", "port")
                )
    for item in grouped.values():
        network_type, confidence, reasons = _classify_candidate(item)
        role_hints = {
            hint for evidence in item['evidence']
            if (hint := _interface_role_hint(evidence.get('interface')))
        }
        item['mixed_network'] = int(len(role_hints) > 1)
        if item['mixed_network']:
            reasons = [*reasons, 'mixed_interface_roles']
            confidence = min(confidence, 0.65)
        item["network_type"] = network_type if network_type in ALLOWED_NETWORK_TYPES else "unclassified"
        item["confidence"] = confidence
        item["classification_reasons"] = reasons
        item["observed_devices"] = sorted(item["observed_devices"])
        item["observed_interfaces"] = sorted(item["observed_interfaces"])
        item["observed_vlans"] = sorted(item["observed_vlans"])
        item["observed_vrfs"] = sorted(item["observed_vrfs"])
    return list(grouped.values())


def _upsert_candidate(conn, candidate: dict[str, Any], collection_run_id: str, now: str) -> str:
    existing = conn.execute(
        """
        SELECT * FROM prefixes
        WHERE prefix = ? AND COALESCE(tenant_id, 'tenant-default') = ?
          AND COALESCE(site_id, '') = ? AND COALESCE(vrf_id, '') = ?
        ORDER BY updated_at DESC LIMIT 1
        """,
        (candidate["prefix"], candidate["tenant_id"], candidate["site_id"], candidate["vrf_id"]),
    ).fetchone()
    evidence_json = _json(candidate.get("evidence"))
    manual = bool(existing and (existing["manual_override"] or existing["source_type"] == "manual"))
    prefix_id = str(existing["id"]) if existing else f"prefix-{uuid.uuid4().hex[:12]}"
    effective_type = str(existing["network_type"] or "unclassified") if manual else candidate["network_type"]
    if existing:
        conn.execute(
            """
            UPDATE prefixes SET network_type = ?, classification_status = ?, classification_source = ?,
                classification_confidence = ?, classification_rule_version = ?, mixed_network = ?, address_roles_json = ?,
                discovered_devices_json = ?, observed_interfaces_json = ?, observed_vlans_json = ?, observed_vrfs_json = ?, evidence_json = ?,
                candidate_scores_json = ?, last_seen_at = ?, miss_count = 0, is_active = 1,
                last_observed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (effective_type, "manual" if manual else "auto", "manual" if manual else "evidence",
             float(existing["classification_confidence"] or 0) if manual else candidate["confidence"],
             CLASSIFICATION_RULE_VERSION, int(candidate.get('mixed_network') or 0), _json(candidate.get('address_roles') or []), _json(candidate["observed_devices"]),
             _json(candidate["observed_interfaces"]), _json(candidate.get("observed_vlans") or []), _json(candidate.get("observed_vrfs") or []), evidence_json,
             _json({candidate["network_type"]: candidate["confidence"]}), now, now, now, prefix_id),
        )
        if not manual and str(existing["network_type"] or "unclassified") != effective_type:
            conn.execute(
                """
                INSERT INTO prefix_classification_history
                    (id, prefix_id, collection_run_id, previous_type, next_type,
                     confidence, source, evidence_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'evidence', ?, ?)
                """,
                (f"prefix-classification-{uuid.uuid4().hex[:12]}", prefix_id, collection_run_id,
                 str(existing["network_type"] or "unclassified"), effective_type,
                 candidate["confidence"], evidence_json, now),
            )
    else:
        conn.execute(
            """
            INSERT INTO prefixes (
                id, prefix, vrf_id, site_id, tenant_id, status, name, network_type,
                traceable, source_type, source_ref, confidence, last_observed_at,
                classification_status, classification_source, classification_confidence,
                classification_rule_version, manual_override, mixed_network,
                address_roles_json, discovered_devices_json, observed_interfaces_json, observed_vlans_json, observed_vrfs_json, evidence_json,
                candidate_scores_json, first_seen_at, last_seen_at, miss_count, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', '', ?, 1, 'discovery', ?, ?, ?, 'auto', 'evidence', ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
            """,
            (prefix_id, candidate["prefix"], candidate["vrf_id"] or None, candidate["site_id"] or None,
             candidate["tenant_id"], effective_type, collection_run_id, candidate["confidence"], now,
             candidate["confidence"], CLASSIFICATION_RULE_VERSION, int(candidate.get('mixed_network') or 0), _json(candidate.get('address_roles') or []),
             _json(candidate["observed_devices"]), _json(candidate["observed_interfaces"]), _json(candidate.get("observed_vlans") or []),
             _json(candidate.get("observed_vrfs") or []), evidence_json,
             _json({candidate["network_type"]: candidate["confidence"]}), now, now, now, now),
        )
    # A prefix may be valid in multiple sites, but that is an explicit data
    # quality finding rather than a silent merge. Keep site ownership in the
    # identity and surface the global tenant/prefix collision to reconciliation.
    conflict_rows = conn.execute(
        """
        SELECT id, site_id FROM prefixes
        WHERE prefix = ? AND COALESCE(tenant_id, 'tenant-default') = ?
          AND COALESCE(site_id, '') <> ?
        """,
        (candidate["prefix"], candidate["tenant_id"], candidate["site_id"]),
    ).fetchall()
    if conflict_rows:
        conflict_payload = {
            "type": "same_prefix_across_sites",
            "prefix": candidate["prefix"],
            "tenant_id": candidate["tenant_id"],
            "sites": sorted({candidate["site_id"]} | {str(row["site_id"] or "") for row in conflict_rows}),
        }
        ids = [prefix_id] + [str(row["id"]) for row in conflict_rows]
        for item_id in ids:
            conn.execute(
                "UPDATE prefixes SET conflict_status = 'cross_site_prefix', conflict_json = ? WHERE id = ?",
                (_json(conflict_payload), item_id),
            )
    return prefix_id


def _derive_address_roles(conn, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach address-level IPAM roles without changing prefix primary usage.

    DHCP leases are scoped by the additive IPAM tenant_id migration; legacy
    rows default to tenant-default.
    """
    network = ipaddress.ip_network(candidate['prefix'], strict=False)
    roles: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            "SELECT address, vip_type, status FROM ipam_vips WHERE COALESCE(tenant_id, 'tenant-default') = ?",
            (candidate['tenant_id'],),
        ).fetchall()
    except Exception:
        rows = []
    for row in rows:
        try:
            address = ipaddress.ip_address(str(row['address']))
        except ValueError:
            continue
        if address in network:
            roles.append({
                'address': str(address),
                'address_role': str(row['vip_type'] or 'service_vip'),
                'status': str(row['status'] or 'active'),
            })
    try:
        lease_rows = conn.execute(
            """
            SELECT address, mac_address, hostname, dhcp_server, lease_state
            FROM ipam_dhcp_leases
            WHERE COALESCE(tenant_id, 'tenant-default') = ?
              AND COALESCE(lease_state, 'active') NOT IN ('released', 'deprecated')
            """,
            (candidate['tenant_id'],),
        ).fetchall()
    except Exception:
        lease_rows = []
    for row in lease_rows:
        try:
            address = ipaddress.ip_address(str(row['address']))
        except ValueError:
            continue
        if address in network:
            roles.append({
                'address': str(address),
                'address_role': 'dhcp_lease',
                'status': str(row['lease_state'] or 'active'),
                'mac_address': str(row['mac_address'] or ''),
                'hostname': str(row['hostname'] or ''),
                'dhcp_server': str(row['dhcp_server'] or ''),
            })
    return roles


def persist_prefix_candidates(candidates: list[dict[str, Any]], *, collection_run_id: str | None = None) -> dict[str, Any]:
    run_id = collection_run_id or f"prefix-discovery-{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = get_db_connection()
    created = 0
    updated = 0
    try:
        for candidate in candidates:
            candidate = {**candidate, 'address_roles': _derive_address_roles(conn, candidate)}
            existing = conn.execute(
                "SELECT id FROM prefixes WHERE prefix = ? AND COALESCE(tenant_id, 'tenant-default') = ? AND COALESCE(site_id, '') = ? AND COALESCE(vrf_id, '') = ? LIMIT 1",
                (candidate["prefix"], candidate["tenant_id"], candidate["site_id"], candidate["vrf_id"]),
            ).fetchone()
            prefix_id = _upsert_candidate(conn, candidate, run_id, now)
            if existing:
                updated += 1
            else:
                created += 1
            for evidence in candidate.get("evidence") or []:
                conn.execute(
                    """
                    INSERT INTO prefix_observations
                        (id, prefix_id, collection_run_id, source_device_id, source_type,
                         observed_value, evidence_json, confidence, first_seen_at, last_seen_at,
                         miss_count, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
                    ON CONFLICT(prefix_id, source_device_id, source_type, observed_value)
                    DO UPDATE SET collection_run_id = excluded.collection_run_id,
                        evidence_json = excluded.evidence_json, confidence = excluded.confidence,
                        last_seen_at = excluded.last_seen_at, miss_count = 0, is_active = 1
                    """,
                    (f"prefix-observation-{uuid.uuid4().hex[:12]}", prefix_id, run_id,
                     evidence.get("device_id") or "", evidence.get("source_type") or "",
                     candidate["prefix"], _json(evidence), candidate["confidence"], now, now),
                )
        conn.commit()
        return {"ok": True, "collection_run_id": run_id, "created": created, "updated": updated, "count": len(candidates)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def age_missing_prefixes(*, collection_run_id: str, started_at: str) -> int:
    """Age discovery-owned prefixes after a complete successful sweep only."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, miss_count FROM prefixes
            WHERE COALESCE(source_type, '') = 'discovery'
              AND COALESCE(manual_override, 0) = 0
              AND COALESCE(last_seen_at, '') < ?
              AND COALESCE(is_active, 1) = 1
            """,
            (started_at,),
        ).fetchall()
        now = _now()
        for row in rows:
            miss_count = int(row["miss_count"] or 0) + 1
            stale = miss_count >= 3
            conn.execute(
                "UPDATE prefixes SET miss_count = ?, is_active = ?, status = ?, updated_at = ? WHERE id = ?",
                (miss_count, 0 if stale else 1, "stale" if stale else "active", now, row["id"]),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def get_prefix_classification_summary() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(classification_status, 'manual') = 'auto' THEN 1 ELSE 0 END) AS auto_count,
                SUM(CASE WHEN COALESCE(manual_override, 0) = 1 OR COALESCE(source_type, '') = 'manual' THEN 1 ELSE 0 END) AS manual_count,
                SUM(CASE WHEN COALESCE(network_type, 'unclassified') = 'unclassified' THEN 1 ELSE 0 END) AS unclassified_count,
                SUM(CASE WHEN COALESCE(mixed_network, 0) = 1 THEN 1 ELSE 0 END) AS mixed_count,
                SUM(CASE WHEN COALESCE(conflict_status, '') <> '' THEN 1 ELSE 0 END) AS conflict_count,
                SUM(CASE WHEN COALESCE(is_active, 1) = 0 OR COALESCE(status, '') = 'stale' THEN 1 ELSE 0 END) AS stale_count
            FROM prefixes
            """
        ).fetchone()
        return {key: int(rows[key] or 0) for key in rows.keys()} if rows else {}
    finally:
        conn.close()


def discover_prefixes_from_interface_snapshot(
    device_id: str,
    *,
    collection_run_id: str | None = None,
) -> dict[str, Any]:
    """Upsert prefixes immediately after a successful interface collection.

    This bridges the CMDB interface collector and IPAM.  The full operational
    discovery job later enriches the same prefixes with routes, LLDP, ARP and
    MAC evidence, while this path makes newly collected interface addresses
    visible without requiring a second manual action in the Prefix page.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT i.interface_name, i.primary_ip, i.ip_address, i.ip_prefix_length,
                   i.vrf_id, d.id AS device_id, d.hostname, d.ip_address AS device_ip,
                   d.platform, d.site_id, d.tenant_id
            FROM interfaces i
            JOIN devices d ON d.id = i.device_id
            WHERE i.device_id = ?
              AND (COALESCE(i.primary_ip, '') <> '' OR COALESCE(i.ip_address, '') <> '')
            ORDER BY i.interface_name
            """,
            (device_id,),
        ).fetchall()
        inventory_rows = conn.execute(
            """
            SELECT inv.ip, inv.interface, inv.mask,
                   d.id AS device_id, d.hostname, d.ip_address AS device_ip,
                   d.platform, d.site_id, d.tenant_id
            FROM ip_inventory inv
            JOIN devices d ON d.id = inv.device_id
            WHERE inv.device_id = ? AND COALESCE(inv.ip, '') <> ''
            ORDER BY inv.last_seen DESC
            """,
            (device_id,),
        ).fetchall()
    finally:
        conn.close()

    inventory_masks: dict[str, str] = {}
    for row in inventory_rows:
        interface_key = normalize_interface_name(row['interface'])
        if interface_key:
            inventory_masks.setdefault(interface_key, str(row['mask'] or ''))

    # CMDB intentionally renders ip_inventory rows when the interface skeleton
    # has not been materialized yet.  Use the same fallback here so Prefix
    # discovery does not depend on a prior status-collection job.
    known_interface_ips = {
        (
            str(row['interface_name'] or '').strip().lower(),
            str(row['primary_ip'] or row['ip_address'] or '').strip().split('/', 1)[0],
        )
        for row in rows
    }
    for inventory_row in inventory_rows:
        interface_name = str(inventory_row['interface'] or '').strip()
        address = str(inventory_row['ip'] or '').strip()
        key = (interface_name.lower(), address.split('/', 1)[0])
        if not interface_name or not address or key in known_interface_ips:
            continue
        rows.append({
            'interface_name': interface_name,
            'primary_ip': address,
            'ip_address': address,
            'ip_prefix_length': str(inventory_row['mask'] or ''),
            'vrf_id': '',
            'device_id': inventory_row['device_id'],
            'hostname': inventory_row['hostname'],
            'device_ip': inventory_row['device_ip'],
            'platform': inventory_row['platform'],
            'site_id': inventory_row['site_id'],
            'tenant_id': inventory_row['tenant_id'],
        })
        known_interface_ips.add(key)

    by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    device = dict(rows[0]) if rows else (dict(inventory_rows[0]) if inventory_rows else {'id': device_id, 'hostname': device_id})
    for row in rows:
        interface_name = str(row['interface_name'] or '')
        raw_ip = str(row['primary_ip'] or row['ip_address'] or '').strip()
        if not raw_ip:
            continue
        prefix_length = str(row['ip_prefix_length'] or '').strip() or inventory_masks.get(
            normalize_interface_name(interface_name),
            '',
        )
        record: dict[str, Any] = {
            'INTERFACE': interface_name,
            'IP_ADDRESS': raw_ip,
            'VRF': str(row['vrf_id'] or ''),
        }
        if prefix_length and '/' not in raw_ip:
            record['PREFIX_LENGTH'] = prefix_length
        tenant_id = str(row['tenant_id'] or 'tenant-default')
        site_id = str(row['site_id'] or '')
        vrf_id = str(row['vrf_id'] or '')
        by_scope[(tenant_id, site_id, vrf_id)].append(record)

    run_id = collection_run_id or f"prefix-interface-{uuid.uuid4().hex[:12]}"
    created = 0
    updated = 0
    count = 0
    for (tenant_id, site_id, vrf_id), records in by_scope.items():
        payload = {
            'device': {
                'id': str(device.get('device_id') or device.get('id') or device_id),
                'hostname': device.get('hostname') or device_id,
                'ip_address': device.get('device_ip') or device.get('ip_address') or '',
                'platform': device.get('platform') or '',
            },
            'categories': [{'key': 'interfaces', 'records': records}],
        }
        candidates = build_prefix_candidates(
            payload,
            tenant_id=tenant_id,
            site_id=site_id,
            vrf_id=vrf_id,
        )
        result = persist_prefix_candidates(candidates, collection_run_id=run_id)
        created += int(result.get('created') or 0)
        updated += int(result.get('updated') or 0)
        count += len(candidates)
    return {
        'ok': True,
        'collection_run_id': run_id,
        'device_id': device_id,
        'created': created,
        'updated': updated,
        'count': count,
    }


def discover_prefixes_for_device(
    device_info: dict[str, Any],
    *,
    tenant_id: str = "tenant-default",
    site_id: str = "",
    vrf_id: str = "",
    payload: dict[str, Any] | None = None,
    collection_run_id: str | None = None,
) -> dict[str, Any]:
    read_only_payload = payload or collect_read_only_evidence(device_info)
    candidates = build_prefix_candidates(read_only_payload, tenant_id=tenant_id, site_id=site_id, vrf_id=vrf_id)
    result = persist_prefix_candidates(candidates, collection_run_id=collection_run_id)
    result.update({"device_id": device_info.get("id"), "candidates": candidates, "collection_status": read_only_payload.get("status")})
    return result


def run_prefix_discovery_job() -> dict[str, Any]:
    """Run a bounded full prefix-evidence sweep for online devices."""
    conn = get_db_connection()
    try:
        devices = [dict(row) for row in conn.execute(
            "SELECT * FROM devices WHERE status = 'online' ORDER BY hostname, ip_address"
        ).fetchall()]
    finally:
        conn.close()

    started_at = _now()
    run_id = f"prefix-discovery-{uuid.uuid4().hex[:12]}"
    result = {"collection_run_id": run_id, "devices": 0, "successful_devices": 0, "failed_devices": 0, "created": 0, "updated": 0}
    for device in devices:
        result["devices"] += 1
        try:
            item = discover_prefixes_for_device(
                device,
                tenant_id=str(device.get("tenant_id") or "tenant-default"),
                site_id=str(device.get("site_id") or ""),
                collection_run_id=run_id,
            )
            result["successful_devices"] += 1
            result["created"] += int(item.get("created") or 0)
            result["updated"] += int(item.get("updated") or 0)
        except Exception:
            result["failed_devices"] += 1
    if result["devices"] and result["failed_devices"] == 0:
        result["aged_prefixes"] = age_missing_prefixes(collection_run_id=run_id, started_at=started_at)
    else:
        result["aged_prefixes"] = 0
    return result
