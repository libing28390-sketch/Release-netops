"""Five-dimension holographic device panorama aggregator for IP Locator & IPAM.

Always reads from authoritative CMDB/IPAM/Topology tables (zero full-table
device walks) and enforces bounded result sizes for ARP/MAC previews.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from core.interface_utils import normalize_interface_name
from database import get_db_connection


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, Mapping) or hasattr(row, "keys"):
        return dict(row)
    return {}


def resolve_vxlan_vtep_leaf(
    conn: Any,
    vtep_ip: str,
    *,
    authorized_device_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Resolve a remote EVPN VXLAN VTEP Loopback IP to its owning Leaf switch."""
    from services.ipam_radix_index_service import get_ipam_radix_index

    idx = get_ipam_radix_index(conn)
    hits = idx.lookup_exact(vtep_ip, authorized_device_ids=authorized_device_ids)
    if not hits:
        return None
    leaf = hits[0]
    return {
        "device_id": leaf.device_id,
        "hostname": leaf.hostname,
        "canonical_mgmt_ip": leaf.canonical_mgmt_ip,
        "vtep_interface": leaf.interface_name,
        "vtep_ip": leaf.ip,
        "vrf": leaf.vrf_name,
    }


def penetrate_vip_real_servers(conn: Any, vip_ip: str, *, tenant_id: str = "") -> list[dict[str, Any]]:
    """Extract backend Real Server IPs registered behind a DNAT / SLB / F5 VIP."""
    try:
        rows = conn.execute(
            """SELECT id, address, vip_type, device_id, real_servers, tenant_id
                 FROM ipam_vips
                WHERE TRIM(address) = ?""",
            (str(vip_ip or "").strip(),),
        ).fetchall()
    except Exception:
        return []
    servers: list[dict[str, Any]] = []
    for raw in rows:
        item = _row_dict(raw)
        if tenant_id and item.get("tenant_id") and str(item["tenant_id"]) != tenant_id:
            continue
        raw_rs = item.get("real_servers")
        parsed_rs: Any = []
        if isinstance(raw_rs, str) and raw_rs.strip():
            try:
                parsed_rs = json.loads(raw_rs)
            except ValueError:
                parsed_rs = [s.strip() for s in raw_rs.split(",") if s.strip()]
        elif isinstance(raw_rs, list):
            parsed_rs = raw_rs
        for entry in parsed_rs or []:
            if isinstance(entry, str):
                servers.append({
                    "real_ip": entry.strip(),
                    "vip_type": str(item.get("vip_type") or "slb"),
                })
            elif isinstance(entry, Mapping):
                ip_val = str(entry.get("ip") or entry.get("address") or entry.get("real_ip") or "").strip()
                if ip_val:
                    servers.append({
                        "real_ip": ip_val,
                        "port": entry.get("port"),
                        "weight": entry.get("weight"),
                        "status": str(entry.get("status") or "unknown"),
                        "vip_type": str(item.get("vip_type") or "slb"),
                    })
    return servers


def get_device_holographic_panorama(
    device_id: str,
    *,
    highlight_port: str = "",
    arp_mac_filter: str = "",
    limit: int = 50,
    conn: Any = None,
) -> dict[str, Any] | None:
    """Build the 5-dimension holographic panorama for one managed network device."""
    owns_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    bounded_limit = min(max(1, int(limit or 50)), 200)
    try:
        dev_row = db.execute(
            """SELECT d.id, d.hostname, d.ip_address, d.status, d.role, d.vendor, d.platform,
                      d.model, d.os_version, d.uptime, d.site_id, d.site, d.tenant_id,
                      COALESCE(NULLIF(BTRIM(d.vsys_id), ''), 'default') AS vsys_id,
                      COALESCE(d.ha_cluster_id, '') AS ha_cluster_id,
                      COALESCE(NULLIF(BTRIM(d.ha_role), ''), 'STANDALONE') AS ha_role,
                      COALESCE(d.base_mac, '') AS base_mac,
                      COALESCE(pa.serial_number, '') AS serial_number,
                      COALESCE(d.site, '') AS physical_location
                 FROM devices d
                 LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
        if not dev_row:
            return None
        dev = _row_dict(dev_row)

        # Dimension 1: Asset & Identity
        asset_identity = {
            "device_id": str(dev["id"]),
            "entity_uid": f"{dev.get('serial_number') or dev['id']}:{dev.get('vsys_id') or 'default'}",
            "hostname": str(dev.get("hostname") or dev["id"]),
            "canonical_mgmt_ip": str(dev.get("ip_address") or ""),
            "status": str(dev.get("status") or "unknown"),
            "role": str(dev.get("role") or ""),
            "vendor": str(dev.get("vendor") or ""),
            "platform": str(dev.get("platform") or ""),
            "model": str(dev.get("model") or ""),
            "os_version": str(dev.get("os_version") or ""),
            "serial_number": str(dev.get("serial_number") or ""),
            "vsys_id": str(dev.get("vsys_id") or "default"),
            "ha_cluster_id": str(dev.get("ha_cluster_id") or ""),
            "ha_role": str(dev.get("ha_role") or "STANDALONE"),
            "base_mac": str(dev.get("base_mac") or ""),
            "uptime": str(dev.get("uptime") or ""),
            "site_id": str(dev.get("site_id") or dev.get("site") or ""),
            "physical_location": str(dev.get("physical_location") or ""),
        }

        # Dimension 2: L3 Interfaces & VRF Matrix
        l3_interfaces: list[dict[str, Any]] = []
        seen_l3: set[tuple[str, str, str]] = set()
        try:
            cmdb_rows = db.execute(
                """SELECT a.interface_name, host(a.ip_address) AS ip_address, a.ip_prefix_length,
                          a.context_type, a.local_context_key,
                          o.interface_type, o.admin_status, o.oper_status, o.description,
                          o.encap_vlan_id, o.duplex
                     FROM cmdb_device_interface_address_observations a
                     JOIN cmdb_collection_snapshots s
                       ON s.device_id = a.device_id
                      AND s.domain = 'interface_inventory'
                      AND s.successful_generation = a.generation
                     LEFT JOIN cmdb_device_interface_observations o
                       ON o.device_id = a.device_id
                      AND o.generation = a.generation
                      AND o.normalized_interface_name = a.normalized_interface_name
                    WHERE a.device_id = ?
                    ORDER BY a.interface_name, a.ip_address""",
                (device_id,),
            ).fetchall()
            for raw in cmdb_rows:
                r = _row_dict(raw)
                vrf = str(r.get("local_context_key") or "default") if str(r.get("context_type") or "").lower() == "vrf" else "default"
                key = (normalize_interface_name(str(r.get("interface_name") or "")).lower(), str(r.get("ip_address") or ""), vrf.lower())
                if key in seen_l3:
                    continue
                seen_l3.add(key)
                l3_interfaces.append({
                    "interface_name": str(r.get("interface_name") or ""),
                    "ip_address": str(r.get("ip_address") or ""),
                    "prefix_length": r.get("ip_prefix_length"),
                    "vrf": vrf,
                    "interface_type": str(r.get("interface_type") or ""),
                    "admin_status": str(r.get("admin_status") or "unknown"),
                    "oper_status": str(r.get("oper_status") or "unknown"),
                    "encap_vlan_id": r.get("encap_vlan_id"),
                    "duplex": str(r.get("duplex") or ""),
                    "description": str(r.get("description") or ""),
                    "source": "cmdb_snapshot",
                })
        except Exception:
            pass

        try:
            if_rows = db.execute(
                """SELECT i.interface_name,
                          COALESCE(NULLIF(BTRIM(i.primary_ip), ''), NULLIF(BTRIM(i.ip_address), '')) AS ip_address,
                          i.ip_prefix_length, i.interface_type, i.speed, i.duplex, i.encap_vlan_id,
                          i.description, i.switchport_mode, i.access_vlan, i.channel_group,
                          COALESCE(i.certified_admin_status, i.admin_status, 'unknown') AS admin_status,
                          COALESCE(i.certified_oper_status, i.oper_status, 'unknown') AS oper_status,
                          COALESCE(v.vrf_name, 'default') AS vrf_name
                     FROM interfaces i
                     LEFT JOIN vrfs v ON v.id = i.vrf_id
                    WHERE i.device_id = ?
                    ORDER BY i.interface_name""",
                (device_id,),
            ).fetchall()
        except Exception:
            if_rows = []

        target_port_diagnostics: dict[str, Any] | None = None
        norm_highlight = normalize_interface_name(highlight_port).lower() if highlight_port else ""
        for raw in if_rows:
            r = _row_dict(raw)
            if_name = str(r.get("interface_name") or "")
            norm_name = normalize_interface_name(if_name).lower()
            if norm_highlight and norm_name == norm_highlight:
                target_port_diagnostics = {
                    "interface_name": if_name,
                    "interface_type": str(r.get("interface_type") or ""),
                    "admin_status": str(r.get("admin_status") or "unknown"),
                    "oper_status": str(r.get("oper_status") or "unknown"),
                    "speed_bps": r.get("speed"),
                    "duplex": str(r.get("duplex") or ""),
                    "switchport_mode": str(r.get("switchport_mode") or ""),
                    "access_vlan": r.get("access_vlan"),
                    "encap_vlan_id": r.get("encap_vlan_id"),
                    "channel_group": r.get("channel_group"),
                    "description": str(r.get("description") or ""),
                }
            ip_val = str(r.get("ip_address") or "").strip()
            if ip_val:
                vrf = str(r.get("vrf_name") or "default")
                key = (norm_name, ip_val, vrf.lower())
                if key not in seen_l3:
                    seen_l3.add(key)
                    l3_interfaces.append({
                        "interface_name": if_name,
                        "ip_address": ip_val,
                        "prefix_length": r.get("ip_prefix_length"),
                        "vrf": vrf,
                        "interface_type": str(r.get("interface_type") or ""),
                        "admin_status": str(r.get("admin_status") or "unknown"),
                        "oper_status": str(r.get("oper_status") or "unknown"),
                        "encap_vlan_id": r.get("encap_vlan_id"),
                        "duplex": str(r.get("duplex") or ""),
                        "description": str(r.get("description") or ""),
                        "source": "interfaces",
                    })

        # Dimension 4: Bounded ARP & MAC Preview (never dumps unbounded tables)
        q = str(arp_mac_filter or "").strip().lower()
        mac_entries: list[dict[str, Any]] = []
        try:
            mac_rows = db.execute(
                """SELECT mac_address, interface_name, vlan_id, entry_type, last_updated
                     FROM mac_table
                    WHERE device_id = ?
                    ORDER BY last_updated DESC
                    LIMIT ?""",
                (device_id, bounded_limit * 2),
            ).fetchall()
            for raw in mac_rows:
                r = _row_dict(raw)
                if norm_highlight and normalize_interface_name(str(r.get("interface_name") or "")).lower() != norm_highlight:
                    if not q:
                        continue
                if q and q not in f"{r.get('mac_address')} {r.get('interface_name')} {r.get('vlan_id')}".lower():
                    continue
                mac_entries.append({
                    "mac": str(r.get("mac_address") or ""),
                    "interface": str(r.get("interface_name") or ""),
                    "vlan": str(r.get("vlan_id") or ""),
                    "type": str(r.get("entry_type") or "dynamic"),
                    "last_updated": str(r.get("last_updated") or ""),
                })
                if len(mac_entries) >= bounded_limit:
                    break
        except Exception:
            pass

        arp_entries: list[dict[str, Any]] = []
        try:
            arp_rows = db.execute(
                """SELECT host(ip_address) AS ip_address, mac_address, interface_name, vlan_key, observed_at
                     FROM ipam_current_endpoint_observations
                    WHERE source_device_id = ? AND observation_source = 'arp'
                    ORDER BY observed_at DESC
                    LIMIT ?""",
                (device_id, bounded_limit * 2),
            ).fetchall()
            for raw in arp_rows:
                r = _row_dict(raw)
                if q and q not in f"{r.get('ip_address')} {r.get('mac_address')} {r.get('interface_name')}".lower():
                    continue
                arp_entries.append({
                    "ip": str(r.get("ip_address") or ""),
                    "mac": str(r.get("mac_address") or ""),
                    "interface": str(r.get("interface_name") or ""),
                    "vlan": str(r.get("vlan_key") or ""),
                    "observed_at": str(r.get("observed_at") or ""),
                })
                if len(arp_entries) >= bounded_limit:
                    break
        except Exception:
            pass

        # Dimension 5: Topology Neighbors
        topology_neighbors: list[dict[str, Any]] = []
        try:
            lnk_rows = db.execute(
                """SELECT source_device_id, source_hostname, source_port,
                          target_device_id, target_hostname, target_port,
                          discovery_source, status, last_seen
                     FROM topology_links
                    WHERE (source_device_id = ? OR target_device_id = ?)
                      AND COALESCE(status, 'up') NOT IN ('down', 'stale', 'inactive', 'deleted')
                    ORDER BY last_seen DESC
                    LIMIT 100""",
                (device_id, device_id),
            ).fetchall()
            for raw in lnk_rows:
                r = _row_dict(raw)
                if str(r.get("source_device_id") or "") == device_id:
                    topology_neighbors.append({
                        "local_port": str(r.get("source_port") or ""),
                        "peer_device_id": str(r.get("target_device_id") or ""),
                        "peer_hostname": str(r.get("target_hostname") or r.get("target_device_id") or ""),
                        "peer_port": str(r.get("target_port") or ""),
                        "protocol": str(r.get("discovery_source") or "lldp"),
                        "last_seen": str(r.get("last_seen") or ""),
                    })
                else:
                    topology_neighbors.append({
                        "local_port": str(r.get("target_port") or ""),
                        "peer_device_id": str(r.get("source_device_id") or ""),
                        "peer_hostname": str(r.get("source_hostname") or r.get("source_device_id") or ""),
                        "peer_port": str(r.get("source_port") or ""),
                        "protocol": str(r.get("discovery_source") or "lldp"),
                        "last_seen": str(r.get("last_seen") or ""),
                    })
        except Exception:
            pass

        return {
            "asset_identity": asset_identity,
            "l3_interfaces": l3_interfaces,
            "target_port_diagnostics": target_port_diagnostics,
            "arp_mac_preview": {
                "arp": arp_entries,
                "mac": mac_entries,
                "limit": bounded_limit,
            },
            "topology_neighbors": topology_neighbors,
        }
    finally:
        if owns_conn:
            db.close()
