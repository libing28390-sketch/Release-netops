"""Collect IP-bearing interface state for the CMDB interface view.

The automation "Interfaces" quick query is the source of truth for the
device-side state.  This worker reuses its command catalog and TextFSM parser,
then enriches the parsed state with NSOT's ``ip_inventory`` so the CMDB
interface projection keeps its historical IP-bearing contract.  Topology
discovery maintains any additional physical/member interface rows it needs
for link identity separately.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.interface_utils import normalize_interface_name
from services.read_only_collection_adapter import collect_read_only_evidence
from services.normalizers.common import interface_type as infer_interface_type

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_value(record: dict[str, Any], *keys: str) -> str:
    # NTC/TextFSM records commonly use lowercase keys while the legacy
    # playbook contract uses uppercase names.  Match case-insensitively so
    # Loopback and other L3 interfaces receive the same status treatment as
    # physical ports.
    normalized = {
        str(record_key).strip().replace('-', '_').upper(): value
        for record_key, value in record.items()
    }
    for key in keys:
        value = normalized.get(str(key).strip().replace('-', '_').upper())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_ip(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"unassigned", "no address", "no", "none", "--", "-", "n/a"}:
        return ""
    try:
        if "/" in raw:
            return str(ipaddress.ip_interface(raw).ip)
        return str(ipaddress.ip_address(raw))
    except ValueError:
        # Keep an address-like value if a vendor emits a valid-looking token
        # with extra presentation text; otherwise reject it as non-IP data.
        candidate = raw.split()[0]
        try:
            return str(ipaddress.ip_address(candidate.split("/")[0]))
        except ValueError:
            return ""


def _normalize_prefix_length(value: Any) -> int | None:
    """Return a validated prefix length from either CIDR length or netmask."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("/"):
        raw = raw[1:].strip()
    try:
        if "." in raw:
            return ipaddress.IPv4Network(f"0.0.0.0/{raw}").prefixlen
        prefix_length = int(raw)
    except (TypeError, ValueError):
        return None
    return prefix_length if 0 <= prefix_length <= 128 else None


def _normalize_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "unknown"
    if any(token in raw for token in ("administratively down", "admin down", "adm", "disabled", "inactive")):
        return "down"
    if "down" in raw or raw in {"notconnect", "not connected", "deleted", "err-disabled"}:
        return "down"
    if "up" in raw or raw in {"connected", "forwarding", "selected", "active"}:
        return "up"
    return "unknown"


_INTERFACE_PREFIXES = (
    "ge", "gigabitethernet", "gi", "eth", "ethernet", "et", "fa", "fastethernet",
    "xge", "tengige", "10ge", "25ge", "40ge", "100ge", "hge", "fge",
    "vlanif", "vlan-interface", "vlan", "svi", "bvi", "irb", "loopback", "loop",
    "lo", "null", "inloopback", "meth", "management", "mgmt", "eth-trunk",
    "bridge-aggregation", "route-aggregation", "port-channel", "portchannel", "tunnel",
)


def _looks_like_interface_name(value: Any) -> bool:
    """Reject parser header fragments such as ``The`` as interface facts."""
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return bool(normalized and any(normalized.startswith(prefix) for prefix in _INTERFACE_PREFIXES)
                and re.search(r"\d", normalized))


def _status_record(record: dict[str, Any], ip_by_interface: dict[str, str]) -> tuple[str, str, str, str]:
    interface_name = _record_value(record, "INTERFACE", "interface", "PORT", "IFNAME")
    key = normalize_interface_name(interface_name)
    ip_value = _normalize_ip(_record_value(record, "IP_ADDRESS", "PRIMARY_IP", "MAIN_IP", "IP", "ADDRESS"))
    if not ip_value:
        ip_value = ip_by_interface.get(key, "")

    # The Playbook/TextFSM families use different field names:
    # Cisco: STATUS + PROTO, Huawei: PHY + PROTOCOL, H3C: LINK + PROTOCOL.
    admin_value = _record_value(record, "STATUS", "LINK", "PHY", "ADMIN_STATUS", "LINK_STATUS")
    oper_value = _record_value(record, "PROTO", "PROTOCOL", "OPER_STATUS", "OPERATE_STATUS")
    return interface_name, ip_value, _normalize_status(admin_value), _normalize_status(oper_value)


def _prefer_status(current: str, candidate: str) -> str:
    """Prefer a concrete status when duplicate parser records are merged."""
    if candidate != "unknown" or current == "unknown":
        return candidate
    return current


def _build_interface_status_rows(
    records: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    descriptions: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build the historical IP-bearing interface snapshot.

    ``display interface brief`` contains L2 ports as well as L3 interfaces,
    but this CMDB collector is intentionally an IP inventory projection.  A
    successful command response containing direct IPs is authoritative; for
    status-only vendor output, retain the known IP-bearing rows from
    ``ip_inventory``.  Topology link discovery is responsible for creating
    physical endpoint rows when it needs them.
    """
    inventory_ips = {key: value.get("ip", "") for key, value in inventory.items()}
    parsed_by_interface: dict[str, dict[str, Any]] = {}
    parser_ip_keys: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        interface_name, direct_ip, admin_status, oper_status = _status_record(record, {})
        if not _looks_like_interface_name(interface_name):
            continue
        key = normalize_interface_name(interface_name)
        if not key:
            continue

        interface_ip = direct_ip or inventory_ips.get(key, "")
        if direct_ip:
            parser_ip_keys.add(key)
        if not interface_ip:
            continue
        parsed = parsed_by_interface.setdefault(
            key,
            {
                "interface_name": interface_name,
                "interface_ip": interface_ip,
                "admin_status": "unknown",
                "oper_status": "unknown",
                "description": None,
            },
        )
        if interface_name and not parsed.get("interface_name"):
            parsed["interface_name"] = interface_name
        if interface_ip and not parsed.get("interface_ip"):
            parsed["interface_ip"] = interface_ip
        parsed["admin_status"] = _prefer_status(parsed["admin_status"], admin_status)
        parsed["oper_status"] = _prefer_status(parsed["oper_status"], oper_status)
        if descriptions.get(key, {}).get("description") is not None:
            parsed["description"] = descriptions[key]["description"]

    # If the vendor response includes direct IPs, it is the current snapshot;
    # otherwise keep the previously discovered IP-bearing inventory rows.
    current_keys = parser_ip_keys or set(inventory)
    rows: list[dict[str, Any]] = []
    for key in sorted(current_keys):
        item = inventory.get(key, {})
        parsed = parsed_by_interface.get(key, {})
        interface_ip = parsed.get("interface_ip") or item.get("ip", "")
        if not interface_ip:
            continue
        rows.append(
            {
                "interface_name": parsed.get("interface_name") or item.get("interface") or key,
                "description": parsed.get("description")
                if parsed
                else descriptions.get(key, {}).get("description"),
                "interface_ip": interface_ip,
                "prefix_length": item.get("prefix_length"),
                "admin_status": parsed.get("admin_status") or "unknown",
                "oper_status": parsed.get("oper_status") or "unknown",
            }
        )
    return parsed_by_interface, rows


def _interface_description(record: dict[str, Any]) -> str | None:
    normalized_keys = {str(key).strip().replace('-', '_').upper() for key in record}
    if not normalized_keys & {"DESCRIPTION", "DESC", "DESCR", "INTERFACE_DESCRIPTION", "NAME_DISPLAY"}:
        return None
    value = _record_value(record, "DESCRIPTION", "DESC", "DESCR", "INTERFACE_DESCRIPTION", "NAME_DISPLAY")
    if not value or value.lower() in {"-", "--", "n/a", "none", "null"}:
        return ""
    compact = re.sub(r"\s+", " ", value).strip()
    # The verbose Huawei/H3C interface parser can capture the following
    # status/MTU line as DESCRIPTION when its free-text tail is misaligned.
    # It is not an operator description and must never enter CMDB.
    if re.search(
        r"(?i)(?:route\s+port|maximum\s+transmit\s+unit|mtu\s*(?:is|:)|"
        r"line\s+protocol|current\s+state|hardware\s+is|internet\s+address)",
        compact,
    ):
        return ""
    return compact


def _description_records(category: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Normalize dedicated TextFSM interface-description records by port."""
    result: dict[str, dict[str, str]] = {}
    for record in category.get("records") or []:
        if not isinstance(record, dict):
            continue
        interface_name = _record_value(record, "INTERFACE", "PORT", "IFNAME", "NAME")
        key = normalize_interface_name(interface_name)
        if not key:
            continue
        description = _interface_description(record)
        if description is not None:
            result[key] = {"interface_name": interface_name, "description": description}
    return result


def _upsert_interface_descriptions(device_id: str, descriptions: dict[str, dict[str, str]]) -> int:
    """Apply a successful dedicated description snapshot to existing CMDB rows."""
    if not descriptions:
        return 0
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT id, interface_name FROM interfaces WHERE device_id = ?", (device_id,)).fetchall()
        existing: dict[str, list[str]] = {}
        for row in rows:
            key = normalize_interface_name(row["interface_name"])
            if key:
                existing.setdefault(key, []).append(row["id"])
        updated = 0
        for key, item in descriptions.items():
            for interface_id in existing.get(key, []):
                conn.execute("UPDATE interfaces SET description = ? WHERE id = ?", (item["description"], interface_id))
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def _friendly_collection_error(exc: BaseException) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if "authentication" in lowered or "password" in lowered or "authorization failed" in lowered:
        return "SSH认证失败，请核查该设备绑定凭据的用户名和密码"
    if "timed out" in lowered or "timeout" in lowered:
        return "SSH连接超时，请检查设备地址、端口和网络连通性"
    if "refused" in lowered or "unreachable" in lowered or "no route" in lowered:
        return "设备不可达，请检查SSH端口和网络连通性"
    if "textfsm" in lowered or "template" in lowered or "parse" in lowered:
        return "接口状态解析失败，请检查平台对应的TextFSM模板"
    return "接口状态采集失败，请查看任务详情或后台日志"


def _load_device(device_id: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row:
            raise ValueError("设备不存在")
        return dict(row)
    finally:
        conn.close()


def _load_ip_inventory(device_id: str) -> dict[str, dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT ip, mask, interface, type, last_seen
               FROM ip_inventory
               WHERE device_id = ? AND COALESCE(ip, '') <> ''""",
            (device_id,),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            key = normalize_interface_name(item.get("interface"))
            ip_value = _normalize_ip(item.get("ip"))
            if key and ip_value:
                result[key] = {
                    **item,
                    "ip": ip_value,
                    "prefix_length": _normalize_prefix_length(item.get("mask")),
                }
        return result
    finally:
        conn.close()


def _upsert_interfaces(device: dict[str, Any], interface_rows: list[dict[str, Any]]) -> int:
    if not interface_rows:
        return 0
    conn = get_db_connection()
    try:
        updated = 0
        observed_at = _now()
        current_keys = {
            normalize_interface_name(item.get("interface_name"))
            for item in interface_rows
            if normalize_interface_name(item.get("interface_name"))
        }
        existing_rows = conn.execute(
            "SELECT id, interface_name FROM interfaces WHERE device_id = ?",
            (device["id"],),
        ).fetchall()
        # A previous collector version could persist both a short and a long
        # vendor alias for the same port.  Update every matching row so a
        # locator query cannot select an older ``unknown`` alias while the
        # canonical row already has a real status.
        existing_by_key: dict[str, list[str]] = {}
        for row in existing_rows:
            key = normalize_interface_name(row["interface_name"])
            if key:
                existing_by_key.setdefault(key, []).append(row["id"])
        # ``interfaces`` is a current-state projection, not a history table.
        # Preserve the row identity for topology references, but remove the
        # address/status snapshot from interfaces that disappeared from the
        # authoritative inventory used by this successful collection.
        for row in existing_rows:
            if normalize_interface_name(row["interface_name"]) not in current_keys:
                conn.execute(
                    """UPDATE interfaces SET
                           primary_ip = '', ip_address = '', ip_prefix_length = NULL,
                           is_l3 = FALSE, ip_enabled = 0,
                           admin_status = 'unknown', oper_status = 'unknown',
                           last_seen = ?
                       WHERE id = ?""",
                    (observed_at, row["id"]),
                )
        for item in interface_rows:
            detected_interface_type = infer_interface_type(item.get("interface_name"))
            interface_ip = item.get("interface_ip") or ""
            l3_enabled = bool(interface_ip) or detected_interface_type in {
                "svi", "loopback", "tunnel", "sub_interface"
            }
            ip_enabled = 1 if interface_ip else 0
            default_mode = "l3" if detected_interface_type in {
                "svi", "loopback", "tunnel", "sub_interface"
            } else "access"
            matching_ids = existing_by_key.get(normalize_interface_name(item["interface_name"]), [])
            if matching_ids:
                for existing_id in matching_ids:
                    conn.execute(
                        """UPDATE interfaces SET
                               description = COALESCE(?, description),
                               admin_status = ?, oper_status = ?,
                               primary_ip = ?, ip_address = ?, is_l3 = ?,
                               ip_enabled = ?,
                               ip_prefix_length = ?,
                               interface_type = CASE
                                   WHEN ? IN ('svi', 'loopback', 'tunnel', 'sub_interface', 'port_channel') THEN ?
                                   ELSE interface_type
                               END,
                               switchport_mode = CASE
                                   WHEN ? IN ('svi', 'loopback', 'tunnel', 'sub_interface') THEN 'l3'
                                   ELSE COALESCE(NULLIF(switchport_mode, ''), ?)
                               END,
                               last_seen = ?
                           WHERE id = ?""",
                        (
                            item.get("description"), item["admin_status"], item["oper_status"], interface_ip,
                            interface_ip, l3_enabled, ip_enabled, item.get("prefix_length"),
                            detected_interface_type, detected_interface_type, detected_interface_type,
                            default_mode, observed_at, existing_id,
                        ),
                    )
                updated += len(matching_ids)
            else:
                conn.execute(
                    """INSERT INTO interfaces (
                           id, device_id, interface_name, description,
                           admin_status, oper_status, interface_type,
                           switchport_mode, primary_ip, ip_address, ip_prefix_length,
                           is_l3, ip_enabled, last_seen
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', item['interface_name']).strip('-').lower()}",
                        device["id"], item["interface_name"], item.get("description") or '', item["admin_status"],
                        item["oper_status"], detected_interface_type, default_mode, interface_ip,
                        interface_ip, item.get("prefix_length"), l3_enabled, ip_enabled, observed_at,
                    ),
                )
                new_id = f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', item['interface_name']).strip('-').lower()}"
                existing_by_key.setdefault(normalize_interface_name(item["interface_name"]), []).append(new_id)
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def collect_interface_status_target(device_id: str) -> dict[str, Any]:
    """Collect one device's interface status and project it into IPAM Prefixes."""
    device = _load_device(device_id)
    inventory = _load_ip_inventory(device_id)
    try:
        # Status and description use separate vendor TextFSM grammars. The
        # dedicated description command is authoritative for this field.
        payload = collect_read_only_evidence(
            device,
            categories=["interfaces", "interface_description", "vlan"],
            auth_role="auto",
        )
    except Exception as exc:
        message = _friendly_collection_error(exc)
        logger.warning("Interface status collection failed for %s: %s", device.get("hostname") or device_id, message, exc_info=True)
        raise RuntimeError(message) from exc

    category = next((item for item in payload.get("categories", []) if item.get("key") == "interfaces"), {})
    if not category.get("success", False):
        raise RuntimeError(str(category.get("error") or "接口状态采集失败"))
    description_category = next(
        (item for item in payload.get("categories", []) if item.get("key") == "interface_description"),
        {},
    )
    descriptions = _description_records(description_category) if description_category.get("success") else {}
    vlan_category = next(
        (item for item in payload.get("categories", []) if item.get("key") == "vlan"),
        {},
    )
    vlan_projection = {"vlans": 0, "interfaces": 0}
    if vlan_category.get("success") and vlan_category.get("parse_status") == "matched":
        try:
            from services.vlan_discovery_service import project_vlan_records
            vlan_projection = project_vlan_records(device_id, vlan_category.get("records") or [])
        except Exception as vlan_exc:
            logger.warning("VLAN member projection failed for %s: %s", device_id, vlan_exc, exc_info=True)
            vlan_projection = {"vlans": 0, "interfaces": 0, "error": str(vlan_exc)}

    parsed_by_interface, rows = _build_interface_status_rows(
        category.get("records") or [], inventory, descriptions
    )

    updated = _upsert_interfaces(device, rows)
    description_updated = 0
    if description_category.get("success") and description_category.get("parse_status") == "matched":
        description_updated = _upsert_interface_descriptions(device_id, descriptions)
    unknown = sum(1 for row in rows if row["admin_status"] == "unknown" or row["oper_status"] == "unknown")
    try:
        from services.prefix_discovery_service import discover_prefixes_from_interface_snapshot

        prefix_sync = discover_prefixes_from_interface_snapshot(
            device_id,
            collection_run_id=f"interface-collection-{device_id}-{payload.get('collected_at') or _now()}",
        )
    except Exception as prefix_exc:
        logger.warning(
            "Prefix sync after interface collection failed for %s: %s",
            device.get("hostname") or device_id,
            prefix_exc,
            exc_info=True,
        )
        prefix_sync = {"ok": False, "error": str(prefix_exc)}
    try:
        from services.vlan_discovery_service import sync_observed_vlans
        vlan_sync = sync_observed_vlans()
    except Exception as vlan_exc:
        logger.warning(
            "VLAN projection after interface collection failed for %s: %s",
            device.get("hostname") or device_id,
            vlan_exc,
            exc_info=True,
        )
        vlan_sync = {"observed": 0, "created": 0, "updated": 0, "error": str(vlan_exc)}
    return {
        "success": True,
        "device_id": device_id,
        "hostname": device.get("hostname") or device_id,
        "interface_count": len(rows),
        "updated_count": updated,
        "description_updated_count": description_updated,
        "vlan_projection": vlan_projection,
        "unknown_status_count": unknown,
        "parsed_count": len(parsed_by_interface),
        "ip_bearing_count": sum(1 for row in rows if row["interface_ip"]),
        "status_only_count": sum(1 for row in rows if not row["interface_ip"]),
        "parser": "textfsm",
        "command": (category.get("commands") or [""])[0],
        "collected_at": payload.get("collected_at") or _now(),
        "prefix_sync": prefix_sync,
        "vlan_sync": vlan_sync,
    }


def collect_interface_status_for_online_devices() -> dict[str, Any]:
    """Refresh CMDB interface status for every online device.

    This is the interface-status phase of the unified Network Reality refresh.
    It also materializes interface skeleton rows for IPs that currently exist
    only in ``ip_inventory``.
    """
    conn = get_db_connection()
    try:
        device_ids = [str(row['id']) for row in conn.execute(
            "SELECT id FROM devices WHERE status = 'online' ORDER BY hostname, ip_address"
        ).fetchall()]
    finally:
        conn.close()

    result: dict[str, Any] = {
        'devices': len(device_ids),
        'succeeded': 0,
        'failed': 0,
        'results': [],
    }
    if not device_ids:
        try:
            from services.vlan_discovery_service import sync_observed_vlans
            result['vlan_sync'] = sync_observed_vlans()
        except Exception as exc:
            logger.warning("VLAN projection after interface collection failed: %s", exc, exc_info=True)
        return result

    with ThreadPoolExecutor(max_workers=min(5, len(device_ids))) as executor:
        futures = {executor.submit(collect_interface_status_target, device_id): device_id for device_id in device_ids}
        for future in as_completed(futures):
            device_id = futures[future]
            try:
                item = future.result()
                result['succeeded'] += 1
                result['results'].append(item)
            except Exception as exc:
                result['failed'] += 1
                result['results'].append({'device_id': device_id, 'success': False, 'error': str(exc)})
                logger.warning("Interface status collection failed for %s: %s", device_id, exc, exc_info=True)
    try:
        from services.vlan_discovery_service import sync_observed_vlans
        result['vlan_sync'] = sync_observed_vlans()
    except Exception as exc:
        result['vlan_sync'] = {'observed': 0, 'created': 0, 'updated': 0, 'error': str(exc)}
        logger.warning("VLAN projection after interface collection failed: %s", exc, exc_info=True)
    return result
