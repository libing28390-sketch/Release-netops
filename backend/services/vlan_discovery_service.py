"""Project observed VLAN facts into the CMDB VLAN inventory.

The collector owns network facts.  Business ownership remains in
``vlan_business_bindings`` and is never overwritten by this service.
"""

from __future__ import annotations

import re
import uuid
import ipaddress
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.interface_utils import normalize_interface_name


_VLAN_INTERFACE_RE = re.compile(
    r"(?:^|[-_. ])(?:vlan(?:if|[-_ ]?interface)?|svi|bvi|bdi|irb|ve|bridge)[-_. ]*(\d+)(?:\.\d+)?$",
    re.IGNORECASE,
)
_VLAN_VALUE_RE = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")
_CISCO_LEGACY_DEFAULT_VLANS = frozenset({1002, 1003, 1004, 1005})
_DEFAULT_VLAN_NAME_MARKERS = frozenset({
    "default",
    "fddi-default",
    "token-ring-default",
    "fddinet-default",
    "trnet-default",
})


def is_system_default_vlan(
    vlan_id: Any,
    name: Any = "",
    *,
    platform: Any = "",
    discovery_source: Any = "",
) -> bool:
    """Return whether a VLAN is vendor/system default rather than business data.

    VLAN 1 is reserved by convention on all supported vendors. Cisco's
    legacy 1002-1005 VLANs are ignored only when Cisco evidence or their
    well-known default names identify them; a manually-created VLAN with the
    same number on another platform is not silently removed.
    """
    try:
        number = int(str(vlan_id or "").strip())
    except (TypeError, ValueError):
        return False
    if number == 1:
        return True
    normalized_name = re.sub(r"\s+", "-", str(name or "").strip().lower())
    if normalized_name in _DEFAULT_VLAN_NAME_MARKERS:
        return True
    normalized_platform = str(platform or "").strip().lower()
    is_cisco = any(token in normalized_platform for token in ("cisco", "ios", "nxos"))
    normalized_source = str(discovery_source or "").strip().lower()
    return number in _CISCO_LEGACY_DEFAULT_VLANS and is_cisco and normalized_source != "manual"


def parse_vlan_id_from_interface(value: Any) -> int | None:
    match = _VLAN_INTERFACE_RE.search(str(value or "").strip())
    if not match:
        return None
    vlan_id = int(match.group(1))
    return vlan_id if 1 <= vlan_id <= 4094 else None


def is_svi_interface(value: Any) -> bool:
    """Return whether an interface name represents a vendor SVI/BDI form.

    Supported names intentionally span common vendor spellings: Cisco/Arista
    ``Vlan``/``BVI``/``BDI``, Huawei ``Vlanif``, H3C ``Vlan-interface``,
    Juniper ``irb.<unit>``, and Brocade-style ``Ve`` interfaces.  This is a
    name-shape check; callers still need usable IP evidence before treating a
    device as an L3 gateway.
    """
    return bool(_VLAN_INTERFACE_RE.search(str(value or "").strip()))


def parse_vlan_values(value: Any) -> set[int]:
    """Parse access/native/allowed VLAN representations conservatively."""
    raw = str(value or "").strip()
    if not raw:
        return set()
    result: set[int] = set()
    for token in re.split(r"[,;\s]+", raw):
        if not token:
            continue
        range_match = re.fullmatch(r"(\d{1,4})-(\d{1,4})", token)
        if range_match:
            start, end = sorted((int(range_match.group(1)), int(range_match.group(2))))
            if end - start <= 4094:
                result.update(v for v in range(start, end + 1) if 1 <= v <= 4094)
            continue
        match = _VLAN_VALUE_RE.fullmatch(token)
        if match:
            vlan_id = int(match.group(1))
            if 1 <= vlan_id <= 4094:
                result.add(vlan_id)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _link_prefixes_to_svis(conn, device_sites: dict[str, str]) -> int:
    """Attach connected prefixes to the VLAN represented by an SVI.

    Prefix discovery intentionally stores evidence JSON first and does not
    assume a VLAN row already exists.  This projection runs after VLAN
    upsert, using the SVI IP/network as deterministic evidence and filling
    the relational fields used by CMDB views.
    """
    vlan_rows = conn.execute("SELECT id, vlan_id, site_id FROM vlans").fetchall()
    vlan_by_scope = {
        (str(row["site_id"] or ""), int(row["vlan_id"])): str(row["id"])
        for row in vlan_rows
        if row["vlan_id"] is not None
    }
    svi_rows = conn.execute(
        """SELECT i.id, i.device_id, i.interface_name, i.primary_ip, i.ip_address,
                  i.ip_prefix_length, i.vrf_id
           FROM interfaces i
           WHERE COALESCE(i.primary_ip, '') <> '' OR COALESCE(i.ip_address, '') <> ''"""
    ).fetchall()
    # The interface collector may receive the SVI name as ``Vlan8`` while the
    # IP inventory collector stores the same H3C interface as
    # ``Vlan-interface8``.  Use the normalized interface identity to recover
    # the mask when the interface projection has no prefix length yet.
    inventory_masks: dict[tuple[str, str], str] = {}
    for row in conn.execute(
        "SELECT device_id, interface, mask FROM ip_inventory WHERE COALESCE(ip, '') <> ''"
    ).fetchall():
        key = (str(row["device_id"] or ""), normalize_interface_name(row["interface"]))
        if key[1] and str(row["mask"] or "").strip():
            inventory_masks.setdefault(key, str(row["mask"]).strip())
    candidates: list[dict[str, Any]] = []
    for row in svi_rows:
        vlan_id = parse_vlan_id_from_interface(row["interface_name"])
        if vlan_id is None:
            continue
        raw_ip = str(row["primary_ip"] or row["ip_address"] or "").strip()
        prefix_length = str(row["ip_prefix_length"] or "").strip()
        if not prefix_length:
            prefix_length = inventory_masks.get(
                (str(row["device_id"] or ""), normalize_interface_name(row["interface_name"])),
                "",
            )
        if not raw_ip or not prefix_length:
            continue
        if "." in prefix_length and "/" not in prefix_length:
            try:
                prefix_length = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_length}").prefixlen)
            except ValueError:
                continue
        try:
            address = ipaddress.ip_interface(f"{raw_ip.split('/', 1)[0]}/{prefix_length}")
        except ValueError:
            continue
        candidates.append({
            "interface_id": str(row["id"]),
            "device_id": str(row["device_id"]),
            "interface_name": str(row["interface_name"]),
            "ip": str(address.ip),
            "network": address.network,
            "vlan_id": vlan_id,
            "site_id": device_sites.get(str(row["device_id"]), ""),
        })

    linked = 0
    for prefix in conn.execute(
        """SELECT id, prefix, gateway, vlan_id, site_id, gateway_device_id,
                  gateway_interface_id, manual_override
           FROM prefixes
           WHERE COALESCE(manual_override, 0) = 0"""
    ).fetchall():
        try:
            prefix_network = ipaddress.ip_network(str(prefix["prefix"]), strict=False)
        except ValueError:
            continue
        scope = str(prefix["site_id"] or "")
        matches = [
            candidate for candidate in candidates
            if candidate["site_id"] == scope and candidate["network"] == prefix_network
        ]
        if not matches:
            gateway = str(prefix["gateway"] or "").strip()
            matches = [candidate for candidate in candidates if candidate["site_id"] == scope and candidate["ip"] == gateway]
        if not matches:
            continue
        candidate = matches[0]
        vlan_pk = vlan_by_scope.get((scope, candidate["vlan_id"]))
        if not vlan_pk:
            continue
        conn.execute(
            """UPDATE prefixes SET vlan_id = ?, gateway = CASE WHEN COALESCE(gateway, '') = '' THEN ? ELSE gateway END,
                      gateway_device_id = CASE WHEN COALESCE(gateway_device_id, '') = '' THEN ? ELSE gateway_device_id END,
                      gateway_interface_id = CASE WHEN COALESCE(gateway_interface_id, '') = '' THEN ? ELSE gateway_interface_id END
               WHERE id = ?""",
            (vlan_pk, candidate["ip"], candidate["device_id"], candidate["interface_id"], prefix["id"]),
        )
        linked += 1
    return linked


def _record_value(record: dict[str, Any], *keys: str) -> Any:
    normalized = {
        str(key).strip().replace('-', '_').lower(): value
        for key, value in record.items()
    }
    for key in keys:
        value = normalized.get(key.lower())
        if value is not None and str(value).strip():
            return value
    return None


def _record_interfaces(record: dict[str, Any]) -> list[str]:
    raw = _record_value(record, "interfaces", "interface", "ports", "port")
    values = raw if isinstance(raw, list) else [raw]
    result: list[str] = []
    for value in values:
        for token in re.split(r"[,;\s]+", str(value or "").strip()):
            token = re.sub(r"^(?:UT|TG):", "", token, flags=re.IGNORECASE)
            token = re.sub(r"\([UD]\)$", "", token, flags=re.IGNORECASE)
            if token and normalize_interface_name(token):
                result.append(token)
    return list(dict.fromkeys(result))


def project_vlan_records(device_id: str, records: list[dict[str, Any]]) -> dict[str, int]:
    """Project TextFSM ``show/display vlan`` records into VLAN and ports.

    Cisco ``show vlan`` reports access members in ``INTERFACES``. Huawei
    ``display vlan`` reports tagged/untagged members using ``TG``/``UT``.
    Both are facts about the physical interface, so they are normalized into
    the same ``interfaces`` VLAN columns.
    """
    if not records:
        return {"vlans": 0, "interfaces": 0}
    conn = get_db_connection()
    try:
        device = conn.execute("SELECT site_id, site, tenant_id, platform, vendor FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not device:
            return {"vlans": 0, "interfaces": 0}
        site_id = str(device["site_id"] or device["site"] or "")
        site_scope = site_id or None
        tenant_id = str(device["tenant_id"] or "tenant-default")
        vlan_count = 0
        interface_count = 0
        now = _now()
        interface_rows_by_key: dict[str, list[dict[str, Any]]] = {}
        for interface_row in conn.execute(
            "SELECT id, interface_name, allowed_vlans FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchall():
            interface_key = normalize_interface_name(interface_row["interface_name"])
            if interface_key:
                interface_rows_by_key.setdefault(interface_key, []).append({
                    "id": interface_row["id"],
                    "interface_name": interface_row["interface_name"],
                    "allowed_vlans": interface_row["allowed_vlans"],
                })
        for record in records:
            if not isinstance(record, dict):
                continue
            raw_vlan = _record_value(record, "vlan_id", "vlan", "vid")
            match = re.search(r"\d+", str(raw_vlan or ""))
            if not match:
                continue
            vlan_id = int(match.group(0))
            if not 1 <= vlan_id <= 4094:
                continue
            vlan_name = str(_record_value(record, "vlan_name", "name", "description") or f"VLAN {vlan_id}").strip()
            if is_system_default_vlan(
                vlan_id,
                vlan_name,
                platform=device["platform"] or device["vendor"],
                discovery_source="vlan_command",
            ):
                continue
            vlan = conn.execute(
                "SELECT id, name FROM vlans WHERE COALESCE(site_id, '') = ? AND vlan_id = ? LIMIT 1",
                (site_id, vlan_id),
            ).fetchone()
            if vlan:
                if not str(vlan["name"] or "").strip() or str(vlan["name"]).strip().lower() == f"vlan {vlan_id}":
                    conn.execute("UPDATE vlans SET name = ?, last_discovered_at = ? WHERE id = ?", (vlan_name, now, vlan["id"]))
            else:
                vlan_id_pk = f"vlan-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT INTO vlans
                       (id, vlan_id, name, site_id, status, tenant_id, discovery_source,
                        first_discovered_at, last_discovered_at, discovery_run_id)
                       VALUES (?, ?, ?, ?, 'active', ?, 'vlan_command', ?, ?, '')""",
                    (vlan_id_pk, vlan_id, vlan_name, site_scope, tenant_id, now, now),
                )
                vlan = {"id": vlan_id_pk, "name": vlan_name}
            vlan_count += 1
            mode = str(_record_value(record, "mode", "port_mode") or "").upper()
            if not mode:
                raw_ports = str(_record_value(record, "ports") or "")
                mode_match = re.search(r"\b(UT|TG):", raw_ports, re.IGNORECASE)
                mode = mode_match.group(1).upper() if mode_match else ""
            for interface_name in _record_interfaces(record):
                interface_key = normalize_interface_name(interface_name)
                if parse_vlan_id_from_interface(interface_name) == vlan_id:
                    matching = interface_rows_by_key.get(interface_key, [])
                    if matching:
                        for existing in matching:
                            conn.execute(
                                "UPDATE interfaces SET interface_type = 'svi', switchport_mode = 'l3', is_l3 = ? WHERE id = ?",
                                (True, existing["id"]),
                            )
                    else:
                        svi_id = f"intf-{uuid.uuid4().hex[:12]}"
                        conn.execute(
                            """INSERT INTO interfaces
                               (id, device_id, interface_name, description, admin_status, oper_status,
                                interface_type, switchport_mode, is_l3, ip_enabled, last_seen)
                               VALUES (?, ?, ?, '', 'unknown', 'unknown', 'svi', 'l3', ?, 0, ?)""",
                             (svi_id, device_id, interface_name, True, now),
                        )
                        interface_rows_by_key.setdefault(interface_key, []).append({
                            "id": svi_id,
                            "interface_name": interface_name,
                            "allowed_vlans": "",
                        })
                    interface_count += 1
                    continue
                matching = interface_rows_by_key.get(interface_key, [])
                if mode == "TG":
                    current: set[int] = set()
                    for existing in matching:
                        current |= parse_vlan_values(existing.get("allowed_vlans"))
                    current.add(vlan_id)
                    allowed = ",".join(str(value) for value in sorted(current))
                    if matching:
                        for existing in matching:
                            conn.execute(
                                "UPDATE interfaces SET switchport_mode = 'trunk', allowed_vlans = ?, last_seen = ? WHERE id = ?",
                                (allowed, now, existing["id"]),
                            )
                            existing["allowed_vlans"] = allowed
                    else:
                        interface_id = f"intf-{uuid.uuid4().hex[:12]}"
                        conn.execute(
                            """INSERT INTO interfaces
                               (id, device_id, interface_name, description, admin_status, oper_status,
                                interface_type, switchport_mode, allowed_vlans, is_l3, ip_enabled, last_seen)
                               VALUES (?, ?, ?, '', 'unknown', 'unknown', 'physical', 'trunk', ?, ?, 0, ?)""",
                             (interface_id, device_id, interface_name, allowed, False, now),
                        )
                        interface_rows_by_key.setdefault(interface_key, []).append({
                            "id": interface_id,
                            "interface_name": interface_name,
                            "allowed_vlans": allowed,
                        })
                else:
                    if matching:
                        for existing in matching:
                            conn.execute(
                                "UPDATE interfaces SET switchport_mode = 'access', access_vlan = ?, interface_type = CASE WHEN interface_type = 'svi' THEN 'svi' ELSE 'physical' END, last_seen = ? WHERE id = ?",
                                (vlan_id, now, existing["id"]),
                            )
                    else:
                        interface_id = f"intf-{uuid.uuid4().hex[:12]}"
                        conn.execute(
                            """INSERT INTO interfaces
                               (id, device_id, interface_name, description, admin_status, oper_status,
                                interface_type, switchport_mode, access_vlan, is_l3, ip_enabled, last_seen)
                               VALUES (?, ?, ?, '', 'unknown', 'unknown', 'physical', 'access', ?, ?, 0, ?)""",
                             (interface_id, device_id, interface_name, vlan_id, False, now),
                        )
                        interface_rows_by_key.setdefault(interface_key, []).append({
                            "id": interface_id,
                            "interface_name": interface_name,
                            "allowed_vlans": "",
                        })
                interface_count += 1
        conn.commit()
        return {"vlans": vlan_count, "interfaces": interface_count}
    finally:
        conn.close()


def sync_observed_vlans() -> dict[str, int]:
    """Upsert VLANs observed by interfaces, ARP or MAC collectors.

    The canonical row is scoped by ``site_id + vlan_id``.  Unknown site data
    uses an empty site scope until the device is assigned to a site.
    """
    conn = get_db_connection()
    try:
        observed: dict[tuple[str, int], set[str]] = {}
        device_sites: dict[str, str] = {}
        device_platforms: dict[str, str] = {}
        for row in conn.execute("SELECT id, site_id, site, platform, vendor FROM devices").fetchall():
            device_sites[str(row["id"])] = str(row["site_id"] or row["site"] or "")
            device_platforms[str(row["id"])] = str(row["platform"] or row["vendor"] or "")

        for row in conn.execute(
            "SELECT device_id, interface_name, access_vlan, native_vlan, allowed_vlans FROM interfaces"
        ).fetchall():
            scope = device_sites.get(str(row["device_id"] or ""), "")
            names = parse_vlan_values(row["access_vlan"]) | parse_vlan_values(row["native_vlan"])
            names |= parse_vlan_values(row["allowed_vlans"])
            svi_vlan = parse_vlan_id_from_interface(row["interface_name"])
            if svi_vlan:
                # Repair stale rows produced by older SNMP/interface jobs.
                # The interface name is deterministic evidence that this is
                # an L3 SVI, independent of whichever collector wrote it.
                conn.execute(
                    "UPDATE interfaces SET interface_type = 'svi', switchport_mode = 'l3', is_l3 = ? WHERE device_id = ? AND interface_name = ?",
                    (True, row["device_id"], row["interface_name"]),
                )
                names.add(svi_vlan)
                source = "interface_svi"
            else:
                source = "interface_vlan"
            for vlan_id in names:
                if is_system_default_vlan(vlan_id, platform=device_platforms.get(str(row["device_id"]), ""), discovery_source=source):
                    continue
                observed.setdefault((scope, vlan_id), set()).add(source)

        for table, source in (("arp_table", "arp_table"), ("mac_table", "mac_table")):
            for row in conn.execute(
                f"SELECT device_id, vlan_id FROM {table} WHERE vlan_id IS NOT NULL"
            ).fetchall():
                vlan_id = int(row["vlan_id"])
                if 1 <= vlan_id <= 4094:
                    scope = device_sites.get(str(row["device_id"] or ""), "")
                    if is_system_default_vlan(
                        vlan_id,
                        platform=device_platforms.get(str(row["device_id"]), ""),
                        discovery_source=source,
                    ):
                        continue
                    observed.setdefault((scope, vlan_id), set()).add(source)

        now = _now()
        created = 0
        updated = 0
        for (site_id, vlan_id), sources in observed.items():
            site_scope = site_id or None
            existing = conn.execute(
                "SELECT id, name, discovery_source, first_discovered_at "
                "FROM vlans WHERE COALESCE(site_id, '') = ? AND vlan_id = ? LIMIT 1",
                (site_id, vlan_id),
            ).fetchone()
            source = "interface_svi" if "interface_svi" in sources else sorted(sources)[0]
            if existing:
                conn.execute(
                    "UPDATE vlans SET "
                    "site_id = COALESCE(NULLIF(site_id, ''), ?), "
                    "name = CASE WHEN COALESCE(name, '') = '' THEN ? ELSE name END, "
                    "status = COALESCE(NULLIF(status, ''), 'active'), "
                    "discovery_source = ?, first_discovered_at = COALESCE(first_discovered_at, ?), "
                    "last_discovered_at = ?, discovery_run_id = ? WHERE id = ?",
                    (site_scope, f"VLAN {vlan_id}", source, now, now, "", existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO vlans "
                    "(id, vlan_id, name, site_id, status, tenant_id, discovery_source, "
                    "first_discovered_at, last_discovered_at, discovery_run_id) "
                    "VALUES (?, ?, ?, ?, 'active', 'tenant-default', ?, ?, ?, ?)",
                    (
                        f"vlan-{uuid.uuid4().hex[:12]}", vlan_id, f"VLAN {vlan_id}",
                        site_scope, source, now, now, "",
                    ),
                )
                created += 1
        linked_prefixes = _link_prefixes_to_svis(conn, device_sites)
        conn.commit()
        return {"observed": len(observed), "created": created, "updated": updated, "linked_prefixes": linked_prefixes}
    finally:
        conn.close()
