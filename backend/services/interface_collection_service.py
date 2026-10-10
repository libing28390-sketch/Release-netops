"""Collect interface state for the CMDB interface view.

IF-MIB provides interface identity, status, speed, alias, MAC address, and MTU.
IP-MIB and Q-BRIDGE-MIB provide address and VLAN facts when their complete
SNMP snapshots are available; the existing CLI categories fill missing domains.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.interface_utils import normalize_interface_name
from services.read_only_collection_adapter import collect_read_only_evidence
from services.normalizers.common import interface_type as infer_interface_type

logger = logging.getLogger(__name__)


class InterfaceInventorySyncError(RuntimeError):
    """Safe, user-facing failure from an on-demand SNMP interface refresh."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously and safely within existing event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


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
    if raw in {"--", "-", "*down", "none"}:
        return "down"
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
    "serial", "pos", "atm", "wlan-ess", "wlan-bss", "aux", "console",
)


def _looks_like_interface_name(value: Any) -> bool:
    """Reject parser header fragments such as ``The`` as interface facts."""
    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return bool(normalized and any(normalized.startswith(prefix) for prefix in _INTERFACE_PREFIXES)
                and re.search(r"\d", normalized))


def _status_record(record: dict[str, Any], ip_by_interface: dict[str, str]) -> tuple[str, str, int | None, str, str]:
    interface_name = _record_value(record, "INTERFACE", "interface", "PORT", "IFNAME", "NAME")
    key = normalize_interface_name(interface_name)
    raw_ip_field = _record_value(record, "IP_ADDRESS", "PRIMARY_IP", "MAIN_IP", "IP", "ADDRESS")
    raw_mask_field = _record_value(record, "MASK", "NETMASK", "PREFIX_LENGTH", "PREFIX_LEN", "SUBNET_MASK", "PREFIX")
    ip_value = _normalize_ip(raw_ip_field)
    if not ip_value:
        ip_value = ip_by_interface.get(key, "")

    prefix_length = None
    if raw_ip_field and "/" in raw_ip_field:
        prefix_length = _normalize_prefix_length(raw_ip_field.split("/", 1)[1])
    elif raw_mask_field:
        prefix_length = _normalize_prefix_length(raw_mask_field)

    # The Playbook/TextFSM families use different field names:
    # Cisco: STATUS + PROTO, Huawei: PHY + PROTOCOL, H3C: LINK + PROTOCOL.
    # Note: In H3C bridge mode, only LINK is present (no PROTOCOL).
    admin_value = _record_value(record, "ADMIN_STATUS", "LINK_STATUS", "LINK", "PHY", "STATUS")
    oper_value = _record_value(record, "OPER_STATUS", "OPERATE_STATUS", "PROTO", "PROTOCOL", "STATUS")

    admin_norm = _normalize_status(admin_value)
    oper_norm = _normalize_status(oper_value)

    # If oper is unknown or unprovided (e.g. L2 bridge port with no protocol, or protocol is "--"),
    # fall back to link/admin state.
    if oper_norm == "unknown" and admin_norm in ("up", "down"):
        oper_norm = admin_norm
    elif admin_norm == "down":
        oper_norm = "down"

    return interface_name, ip_value, prefix_length, admin_norm, oper_norm


def _prefer_status(current: str, candidate: str) -> str:
    """Prefer a concrete status when duplicate parser records are merged."""
    if candidate != "unknown" or current == "unknown":
        return candidate
    return current


def _build_interface_status_rows(
    records: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    descriptions: dict[str, dict[str, str]],
    address_records: list[dict[str, Any]] | None = None,
    *,
    address_snapshot_available: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build the historical IP-bearing interface snapshot.

    ``display interface brief`` contains L2 ports as well as L3 interfaces,
    but this CMDB collector is intentionally an IP inventory projection.  A
    a complete IP-MIB snapshot is authoritative; for status-only output,
    retain known IP-bearing rows from ``ip_inventory``. Topology link discovery
    is responsible for creating physical endpoint rows when it needs them.
    """
    inventory_ips = {key: value.get("ip", "") for key, value in inventory.items()}
    address_ips: dict[str, str] = {}
    address_prefixes: dict[str, int | None] = {}
    for address in address_records or []:
        if not isinstance(address, dict):
            continue
        key = normalize_interface_name(address.get("interface"))
        ip_address = _normalize_ip(address.get("ip_address"))
        if key and ip_address:
            address_ips.setdefault(key, ip_address)
            address_prefixes.setdefault(key, _normalize_prefix_length(address.get("prefix_length")))
    ip_by_interface = address_ips if address_snapshot_available else inventory_ips
    parsed_by_interface: dict[str, dict[str, Any]] = {}
    parser_ip_keys: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        interface_name, direct_ip, direct_prefix_len, admin_status, oper_status = _status_record(record, ip_by_interface)
        if not _looks_like_interface_name(interface_name):
            continue
        key = normalize_interface_name(interface_name)
        if not key:
            continue

        if address_snapshot_available and key in address_ips:
            direct_ip = address_ips[key]
            direct_prefix_len = address_prefixes.get(key)

        interface_ip = direct_ip or ip_by_interface.get(key, "")
        if direct_ip:
            parser_ip_keys.add(key)
        if not interface_ip:
            continue
        parsed = parsed_by_interface.setdefault(
            key,
            {
                "interface_name": interface_name,
                "interface_ip": interface_ip,
                "prefix_length": direct_prefix_len if direct_prefix_len is not None else address_prefixes.get(key),
                "admin_status": "unknown",
                "oper_status": "unknown",
                "description": None,
            },
        )
        if interface_name and not parsed.get("interface_name"):
            parsed["interface_name"] = interface_name
        if interface_ip and not parsed.get("interface_ip"):
            parsed["interface_ip"] = interface_ip
        if direct_prefix_len is not None:
            parsed["prefix_length"] = direct_prefix_len
        parsed["admin_status"] = _prefer_status(parsed["admin_status"], admin_status)
        parsed["oper_status"] = _prefer_status(parsed["oper_status"], oper_status)
        record_description = _record_value(record, "DESCRIPTION", "ALIAS", "IF_ALIAS")
        if record_description:
            parsed["description"] = record_description
        elif descriptions.get(key, {}).get("description") is not None:
            parsed["description"] = descriptions[key]["description"]

    # If the vendor response includes direct IPs, it is the current snapshot;
    # otherwise keep the previously discovered IP-bearing inventory rows.
    current_keys = set(address_ips) if address_snapshot_available else (parser_ip_keys or set(inventory))
    rows: list[dict[str, Any]] = []
    for key in sorted(current_keys):
        item = inventory.get(key, {})
        parsed = parsed_by_interface.get(key, {})
        interface_ip = parsed.get("interface_ip") or ip_by_interface.get(key, "") or item.get("ip", "")
        if not interface_ip:
            continue
        resolved_prefix_length = parsed.get("prefix_length")
        if resolved_prefix_length is None:
            resolved_prefix_length = item.get("prefix_length")
        rows.append(
            {
                "interface_name": parsed.get("interface_name") or item.get("interface") or key,
                "description": parsed.get("description")
                if parsed
                else descriptions.get(key, {}).get("description"),
                "interface_ip": interface_ip,
                "prefix_length": resolved_prefix_length,
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
        row = conn.execute(
            """SELECT d.*,
                      COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS canonical_asset_type,
                      COALESCE(NULLIF(d.device_category, ''), NULLIF(pa.device_category, ''), '') AS canonical_device_category,
                      COALESCE(NULLIF(d.platform, ''), NULLIF(pa.platform, ''), '') AS canonical_platform,
                      COALESCE(NULLIF(d.role, ''), NULLIF(pa.device_role, ''), '') AS canonical_role
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
        if not row:
            raise ValueError("设备不存在")
        return dict(row)
    finally:
        conn.close()


def is_online_network_device_for_interface_collection(device: dict[str, Any]) -> bool:
    """Apply the CMDB asset type and shared server classification to manual targets."""
    if str(device.get("status") or "").strip().casefold() != "online":
        return False
    asset_type = str(
        device.get("canonical_asset_type") or device.get("asset_type") or "network_device"
    ).strip().casefold()
    if asset_type != "network_device":
        return False

    from services.device_classification_service import is_server_device

    classification_device = {
        **device,
        "device_category": device.get("canonical_device_category") or device.get("device_category"),
        "platform": device.get("canonical_platform") or device.get("platform"),
        "role": device.get("canonical_role") or device.get("role"),
    }
    return not is_server_device(classification_device)


def _load_ip_inventory(device_id: str) -> dict[str, dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT ip, mask, interface, type, last_seen
               FROM ip_inventory
               WHERE device_id = ? AND COALESCE(ip, '') <> ''
               ORDER BY interface, ip""",
            (device_id,),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            key = normalize_interface_name(item.get("interface"))
            ip_value = _normalize_ip(item.get("ip"))
            if key and ip_value:
                candidate = {
                    **item,
                    "ip": ip_value,
                    "prefix_length": _normalize_prefix_length(item.get("mask")),
                }
                previous = result.get(key)
                candidate_rank = (ipaddress.ip_address(ip_value).version, ip_value)
                previous_rank = (
                    ipaddress.ip_address(previous["ip"]).version,
                    previous["ip"],
                ) if previous else None
                if previous_rank is None or candidate_rank < previous_rank:
                    result[key] = candidate
        return result
    finally:
        conn.close()


def _collect_snmp_interface_domains(
    device: dict[str, Any],
    *,
    collect_interfaces: bool,
    collect_vlans: bool,
) -> dict[str, Any]:
    """Collect independent IF-MIB, IP-MIB, and Q-BRIDGE-MIB fact domains."""
    result: dict[str, Any] = {
        "configured": False,
        "interfaces": None,
        "addresses": None,
        "vlan_data": None,
        "complete": {
            "interface_status": False,
            "interface_description": False,
            "interface_mac": False,
            "interface_mtu": False,
            "interface_addresses": False,
            "vlan": False,
        },
        "errors": {},
        "version": None,
    }
    try:
        from services.vault_service import resolve_collector_credentials
        from services.snmp_service import (
            collect_interface_ip_addresses,
            collect_interface_status_data,
            collect_qbridge_interface_vlan_data,
        )

        creds = resolve_collector_credentials(device)
        snmp_cred = creds.get("snmp") or {}
        if not snmp_cred.get("configured"):
            result["errors"]["credentials"] = "not_configured"
            return result

        target_ip = snmp_cred.get("server") or str(device.get("ip_address") or "").strip()
        if not target_ip:
            result["errors"]["credentials"] = "target_missing"
            return result

        version = str(snmp_cred.get("version") or "2c").strip().casefold()
        is_v3 = version in {"3", "v3", "snmpv3"}
        community_or_profile = dict(snmp_cred) if is_v3 else str(snmp_cred.get("community") or "")
        if not is_v3 and not community_or_profile:
            result["errors"]["credentials"] = "community_missing"
            return result
        port = int(snmp_cred.get("port") or 161)
        result.update({"configured": True, "version": version})

        interfaces: list[dict[str, Any]] | None = None
        interface_names_by_index: dict[int, str] = {}
        if collect_interfaces:
            try:
                collected = _run_async(collect_interface_status_data(
                    target_ip,
                    community=community_or_profile,
                    port=port,
                    version=version,
                    timeout=8,
                ))
                if not isinstance(collected, list) or not collected:
                    raise RuntimeError("IF-MIB returned no interface rows")
                interfaces = [item for item in collected if isinstance(item, dict)]
                if not interfaces:
                    raise RuntimeError("IF-MIB returned no usable interface rows")
                for item in interfaces:
                    try:
                        if_index = int(item.get("if_index"))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    name = str(item.get("name") or "").strip()
                    if if_index > 0 and name:
                        interface_names_by_index[if_index] = name
                result["interfaces"] = interfaces
                result["complete"]["interface_status"] = True
                result["complete"]["interface_description"] = all(
                    item.get("description_available") is not False for item in interfaces
                )
                result["complete"]["interface_mac"] = all(
                    item.get("mac_address_available") is True for item in interfaces
                )
                result["complete"]["interface_mtu"] = all(
                    item.get("mtu_available") is True for item in interfaces
                )
            except Exception as exc:
                result["errors"]["interface_status"] = type(exc).__name__

        if collect_interfaces:
            try:
                addresses = _run_async(collect_interface_ip_addresses(
                    target_ip,
                    community_or_profile,
                    interface_names_by_index,
                    port,
                    version=version,
                    timeout=8,
                ))
                if not isinstance(addresses, list) or not addresses:
                    raise RuntimeError("IP-MIB returned no usable interface addresses")
                result["addresses"] = addresses
                result["complete"]["interface_addresses"] = True
            except Exception as exc:
                result["errors"]["interface_addresses"] = type(exc).__name__

        if collect_vlans:
            try:
                vlan_data = _run_async(collect_qbridge_interface_vlan_data(
                    target_ip,
                    community_or_profile,
                    interface_names_by_index or None,
                    port,
                    version=version,
                    timeout=8,
                ))
                if not isinstance(vlan_data, dict) or not vlan_data.get("vlans") or not vlan_data.get("interfaces"):
                    raise RuntimeError("Q-BRIDGE returned no complete VLAN membership rows")
                result["vlan_data"] = vlan_data
                result["complete"]["vlan"] = True
            except Exception as exc:
                result["errors"]["vlan"] = type(exc).__name__
        return result
    except Exception as exc:
        # Credential resolution and address/profile errors make every requested
        # domain unavailable; callers retain prior snapshots and use fallback.
        for domain in ("interface_status", "interface_addresses", "vlan"):
            if (collect_interfaces and domain.startswith("interface_")) or (collect_vlans and domain == "vlan"):
                result["errors"].setdefault(domain, type(exc).__name__)
        return result


def _collect_snmp_interfaces(device: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Collect the lightweight IF-MIB interface snapshot when SNMP is configured."""
    try:
        from services.vault_service import resolve_collector_credentials
        from services.snmp_service import collect_interface_status_data

        creds = resolve_collector_credentials(device)
        snmp_cred = creds.get("snmp") or {}
        if not snmp_cred.get("configured"):
            return None

        target_ip = snmp_cred.get("server") or str(device.get("ip_address") or "").strip()
        if not target_ip:
            return None

        version = str(snmp_cred.get("version") or "2c").strip().casefold()
        is_v3 = version in {"3", "v3", "snmpv3"}
        community_or_profile = dict(snmp_cred) if is_v3 else str(snmp_cred.get("community") or "")
        if not is_v3 and not community_or_profile:
            return None
        port = int(snmp_cred.get("port") or 161)
        interfaces = _run_async(collect_interface_status_data(
            target_ip,
            community=community_or_profile,
            port=port,
            version=version,
            timeout=8,
        ))
        return interfaces if isinstance(interfaces, list) and interfaces else None
    except Exception as exc:
        logger.info(
            "SNMP interface collection for %s failed (%s), falling back to CLI",
            device.get("hostname") or device.get("id"),
            type(exc).__name__,
        )
        return None


def refresh_snmp_interface_inventory(device_id: str) -> dict[str, Any]:
    """Read one device's IF-MIB inventory and persist its interface names/indexes.

    This narrow, user-triggered operation intentionally avoids the all-device
    CLI interface-status job and does not collect unrelated health metrics.
    """
    device = _load_device(device_id)
    try:
        from services.vault_service import resolve_collector_credentials

        credentials = resolve_collector_credentials(device)
    except Exception as exc:
        logger.warning("SNMP interface credential resolution failed for %s (%s)", device_id, type(exc).__name__)
        raise InterfaceInventorySyncError(
            "snmp_credentials_unavailable",
            "无法读取设备的 SNMP 凭据，请检查该设备的凭据配置。",
        ) from exc

    snmp_credentials = (credentials or {}).get("snmp") or {}
    if not snmp_credentials.get("configured"):
        raise InterfaceInventorySyncError(
            "snmp_not_configured",
            "该设备尚未配置可用的 SNMP 只读凭据。",
        )

    target_ip = str(snmp_credentials.get("server") or device.get("ip_address") or "").strip()
    if not target_ip:
        raise InterfaceInventorySyncError("device_ip_missing", "设备未配置可用于 SNMP 采集的地址。")
    try:
        port = int(snmp_credentials.get("port") or 161)
    except (TypeError, ValueError) as exc:
        raise InterfaceInventorySyncError("snmp_port_invalid", "设备的 SNMP 端口配置无效。") from exc

    try:
        from services.snmp_service import collect_interface_inventory

        version = str(snmp_credentials.get("version") or "2c").strip().casefold()
        is_v3 = version in {"3", "v3", "snmpv3"}
        community_or_profile = dict(snmp_credentials) if is_v3 else str(snmp_credentials.get("community") or "")
        if not is_v3 and not community_or_profile:
            raise ValueError("SNMP community is missing")
        collected = _run_async(
            collect_interface_inventory(
                target_ip,
                community=community_or_profile,
                port=port,
                version=version,
            )
        )
    except Exception as exc:
        logger.info("On-demand SNMP interface refresh failed for %s (%s)", device_id, type(exc).__name__)
        raise InterfaceInventorySyncError(
            "snmp_interface_read_failed",
            "读取设备端口失败，请检查 SNMP 连通性和只读权限。",
        ) from exc

    valid_interfaces = []
    for item in collected or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        raw_index = item.get("if_index", item.get("index"))
        try:
            if_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if name and if_index > 0 and _looks_like_interface_name(name):
            valid_interfaces.append({**item, "if_index": if_index})
    if not valid_interfaces:
        raise InterfaceInventorySyncError(
            "snmp_no_valid_interfaces",
            "设备没有返回可用于监控的端口，请检查 SNMP 只读视图是否开放 IF-MIB。",
        )

    updated_count = _upsert_snmp_interfaces(device, valid_interfaces)
    if updated_count <= 0:
        raise InterfaceInventorySyncError(
            "snmp_interface_persist_failed",
            "读取到了端口，但未能保存到设备清单，请稍后重试。",
        )
    return {
        "device_id": device_id,
        "interface_count": len(valid_interfaces),
        "updated_count": updated_count,
    }


def _upsert_snmp_interfaces(device: dict[str, Any], snmp_interfaces: list[dict[str, Any]]) -> int:
    """Synchronize raw SNMP IF-MIB interface inventory and physical status into CMDB."""
    if not snmp_interfaces:
        return 0
    conn = get_db_connection()
    try:
        updated = 0
        observed_at = _now()
        existing_rows = conn.execute(
            "SELECT id, interface_name, admin_status, oper_status, speed, description FROM interfaces WHERE device_id = ?",
            (device["id"],),
        ).fetchall()

        existing_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in existing_rows:
            key = normalize_interface_name(row["interface_name"])
            if key:
                existing_by_key.setdefault(key, []).append(dict(row))

        for item in snmp_interfaces:
            raw_name = str(item.get("name") or "").strip()
            if not raw_name or not _looks_like_interface_name(raw_name):
                continue
            key = normalize_interface_name(raw_name)
            if not key:
                continue

            admin_stat = _normalize_status(item.get("admin_status") or item.get("status"))
            oper_stat = _normalize_status(item.get("status") or item.get("oper_status"))
            if oper_stat == "unknown" and admin_stat in ("up", "down"):
                oper_stat = admin_stat

            speed_mbps = item.get("speed_mbps") or 0
            try:
                speed_bps = int(speed_mbps * 1_000_000) if speed_mbps else None
            except (TypeError, ValueError):
                speed_bps = None

            description = str(item.get("description") or "").strip()
            mac_address = str(item.get("mac_address") or "").strip().lower()
            try:
                mtu_value = int(item.get("mtu"))
                mtu_value = mtu_value if mtu_value > 0 else None
            except (TypeError, ValueError, OverflowError):
                mtu_value = None
            if_index = item.get("if_index", item.get("index"))
            try:
                parsed_if_index = int(if_index) if str(if_index or "").isdigit() else 0
                if_index_val = parsed_if_index if parsed_if_index > 0 else None
            except (TypeError, ValueError):
                if_index_val = None

            matching = existing_by_key.get(key, [])
            if matching:
                for existing in matching:
                    conn.execute(
                        """UPDATE interfaces SET
                               admin_status = CASE WHEN ? <> 'unknown' THEN ? ELSE admin_status END,
                               oper_status = CASE WHEN ? <> 'unknown' THEN ? ELSE oper_status END,
                               speed = COALESCE(?, speed),
                               mac_address = CASE WHEN ? <> '' THEN ? ELSE mac_address END,
                               mtu = CASE WHEN ? IS NOT NULL THEN ? ELSE mtu END,
                               description = CASE WHEN ? <> '' THEN ? ELSE description END,
                               if_index = COALESCE(?, if_index),
                               last_seen = ?
                           WHERE id = ?""",
                        (
                            admin_stat, admin_stat,
                            oper_stat, oper_stat,
                            speed_bps,
                            mac_address, mac_address,
                            mtu_value, mtu_value,
                            description, description,
                            if_index_val,
                            observed_at,
                            existing["id"],
                        ),
                    )
                    updated += 1
            else:
                detected_type = infer_interface_type(raw_name)
                default_mode = "l3" if detected_type in {
                    "svi", "loopback", "tunnel", "sub_interface"
                } else "access"
                new_id = f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', raw_name).strip('-').lower()}"
                conn.execute(
                    """INSERT INTO interfaces (
                           id, device_id, interface_name, description, mac_address, mtu,
                           admin_status, oper_status, speed, if_index,
                           interface_type, switchport_mode, is_l3, ip_enabled, last_seen
                       ) VALUES (?, ?, ?, ?, ?, COALESCE(?, 1500), ?, ?, ?, ?, ?, ?, FALSE, 0, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           admin_status = excluded.admin_status,
                           oper_status = excluded.oper_status,
                           speed = COALESCE(excluded.speed, interfaces.speed),
                           mac_address = CASE WHEN excluded.mac_address <> '' THEN excluded.mac_address ELSE interfaces.mac_address END,
                           mtu = CASE WHEN ? IS NOT NULL THEN excluded.mtu ELSE interfaces.mtu END,
                           if_index = COALESCE(excluded.if_index, interfaces.if_index),
                           description = CASE WHEN excluded.description <> '' THEN excluded.description ELSE interfaces.description END,
                           last_seen = excluded.last_seen""",
                    (
                        new_id, device["id"], raw_name, description, mac_address, mtu_value,
                        admin_stat, oper_stat, speed_bps,
                        if_index_val,
                        detected_type, default_mode, observed_at,
                        mtu_value,
                    ),
                )
                existing_by_key.setdefault(key, []).append({"id": new_id, "interface_name": raw_name})
                updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()


def _upsert_snmp_ip_inventory(device_id: str, addresses: list[dict[str, Any]]) -> int:
    """Replace one complete IP-MIB snapshot without flattening multi-address ports."""
    if not addresses:
        raise ValueError("An empty IP-MIB snapshot is not authoritative")
    normalized_by_ip: dict[str, dict[str, Any]] = {}
    for item in addresses:
        ip_value = _normalize_ip(item.get("ip_address"))
        interface_name = str(item.get("interface") or "").strip()
        if not ip_value or not interface_name:
            raise ValueError("IP-MIB snapshot contains an invalid address or interface")
        current = normalized_by_ip.get(ip_value)
        if current and normalize_interface_name(current["interface"]) != normalize_interface_name(interface_name):
            raise ValueError("ip_inventory cannot represent one IP assigned to multiple interfaces")
        normalized_by_ip[ip_value] = {**item, "ip_address": ip_value, "interface": interface_name}

    conn = get_db_connection()
    try:
        observed_at = _now()
        conn.execute("DELETE FROM ip_inventory WHERE device_id = ?", (device_id,))
        for ip_value, item in sorted(normalized_by_ip.items()):
            address = ipaddress.ip_address(ip_value)
            prefix_length = _normalize_prefix_length(item.get("prefix_length"))
            if prefix_length is not None and prefix_length > address.max_prefixlen:
                raise ValueError("IP-MIB snapshot contains a prefix outside its address family")
            if prefix_length is None:
                mask = ""
            elif address.version == 4:
                mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_length}").netmask)
            else:
                # The existing IPAM mask column is textual and readers accept
                # either a prefix length or a netmask for IPv6.
                mask = str(prefix_length)
            interface_type = infer_interface_type(item["interface"]) or "physical"
            cursor = conn.execute(
                """INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ip) DO UPDATE SET
                       mask = excluded.mask,
                       interface = excluded.interface,
                       type = excluded.type,
                       last_seen = excluded.last_seen
                   WHERE ip_inventory.device_id = excluded.device_id""",
                (ip_value, mask, device_id, item["interface"], interface_type, observed_at),
            )
            if getattr(cursor, "rowcount", 1) == 0:
                raise ValueError("ip_inventory already assigns this IP to another device")
        conn.commit()
        return len(normalized_by_ip)
    finally:
        conn.close()


def _upsert_qbridge_vlan_data(device_id: str, data: dict[str, Any]) -> dict[str, int]:
    """Persist a complete Q-BRIDGE snapshot using the existing VLAN projection."""
    vlan_records = data.get("vlans") or []
    interface_records = data.get("interfaces") or []
    if not vlan_records or not interface_records:
        raise ValueError("An incomplete Q-BRIDGE snapshot is not authoritative")

    from services.vlan_discovery_service import is_system_default_vlan

    conn = get_db_connection()
    try:
        device_row = conn.execute(
            "SELECT site_id, site, tenant_id, platform, vendor FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if not device_row:
            raise ValueError("VLAN snapshot device does not exist")
        site_id = str(device_row["site_id"] or device_row["site"] or "")
        site_scope = site_id or None
        tenant_id = str(device_row["tenant_id"] or "tenant-default")
        platform = str(device_row["platform"] or device_row["vendor"] or "")
        observed_at = _now()
        vlan_count = 0
        for item in vlan_records:
            try:
                vlan_number = int(item.get("vlan_id"))
            except (TypeError, ValueError, OverflowError):
                raise ValueError("Q-BRIDGE snapshot contains an invalid VLAN ID")
            if not 1 <= vlan_number <= 4094:
                raise ValueError("Q-BRIDGE snapshot contains a VLAN ID outside 1..4094")
            vlan_name = str(item.get("vlan_name") or f"VLAN {vlan_number}").strip()
            if is_system_default_vlan(
                vlan_number,
                vlan_name,
                platform=platform,
                discovery_source="qbridge_snmp",
            ):
                continue
            existing = conn.execute(
                "SELECT id, name FROM vlans WHERE COALESCE(site_id, '') = ? AND vlan_id = ? LIMIT 1",
                (site_id, vlan_number),
            ).fetchone()
            if existing:
                old_name = str(existing["name"] or "").strip()
                if not old_name or old_name.casefold() == f"vlan {vlan_number}".casefold():
                    conn.execute(
                        "UPDATE vlans SET name = ?, last_discovered_at = ? WHERE id = ?",
                        (vlan_name, observed_at, existing["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE vlans SET last_discovered_at = ? WHERE id = ?",
                        (observed_at, existing["id"]),
                    )
            else:
                conn.execute(
                    """INSERT INTO vlans
                       (id, vlan_id, name, site_id, status, tenant_id, discovery_source,
                        first_discovered_at, last_discovered_at, discovery_run_id)
                       VALUES (?, ?, ?, ?, 'active', ?, 'qbridge_snmp', ?, ?, '')""",
                    (
                        f"vlan-{uuid.uuid4().hex[:12]}", vlan_number, vlan_name,
                        site_scope, tenant_id, observed_at, observed_at,
                    ),
                )
            vlan_count += 1

        rows = conn.execute(
            "SELECT id, interface_name FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchall()
        interfaces_by_key: dict[str, list[str]] = {}
        for row in rows:
            key = normalize_interface_name(row["interface_name"])
            if key:
                interfaces_by_key.setdefault(key, []).append(row["id"])

        updated_interfaces = 0
        inferred_modes = 0
        for item in interface_records:
            interface_name = str(item.get("interface") or "").strip()
            interface_key = normalize_interface_name(interface_name)
            try:
                if_index = int(item.get("if_index"))
                pvid = int(item.get("pvid"))
            except (TypeError, ValueError, OverflowError):
                raise ValueError("Q-BRIDGE port snapshot contains an invalid ifIndex or PVID")
            if not interface_name or not interface_key or if_index <= 0 or not 1 <= pvid <= 4094:
                raise ValueError("Q-BRIDGE port snapshot contains an invalid interface row")

            try:
                tagged = {int(value) for value in (item.get("tagged_vlans") or [])}
                untagged = {int(value) for value in (item.get("untagged_vlans") or [])}
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Q-BRIDGE port snapshot contains an invalid VLAN membership") from exc
            if any(not 1 <= value <= 4094 for value in tagged | untagged):
                raise ValueError("Q-BRIDGE port snapshot contains a VLAN membership outside 1..4094")

            matching_ids = interfaces_by_key.get(interface_key, [])
            if not matching_ids:
                detected_type = infer_interface_type(interface_name) or "physical"
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", interface_name).strip("-").lower()
                new_id = f"intf-{device_id}-{slug}"
                conn.execute(
                    """INSERT INTO interfaces
                       (id, device_id, interface_name, admin_status, oper_status, interface_type,
                        switchport_mode, vlan_mode, if_index, ip_enabled, is_l3, last_seen)
                       VALUES (?, ?, ?, 'unknown', 'unknown', ?, 'unknown', 'unknown', ?, 0, FALSE, ?)""",
                    (new_id, device_id, interface_name, detected_type, if_index, observed_at),
                )
                matching_ids = [new_id]
                interfaces_by_key[interface_key] = matching_ids

            access = (tagged | untagged) == {pvid} and tagged == set() and untagged == {pvid}
            native_vlan = next(iter(untagged)) if len(untagged) == 1 and untagged == {pvid} else None
            trunk = bool(tagged) and len(untagged) <= 1 and (not untagged or untagged == {pvid})
            for interface_id in matching_ids:
                if access:
                    conn.execute(
                        """UPDATE interfaces SET if_index = ?, switchport_mode = 'access', vlan_mode = 'access',
                               access_vlan = ?, native_vlan = NULL, allowed_vlans = '', last_seen = ?
                           WHERE id = ?""",
                        (if_index, pvid, observed_at, interface_id),
                    )
                    inferred_modes += 1
                elif trunk:
                    allowed_vlans = ",".join(str(value) for value in sorted(tagged))
                    conn.execute(
                        """UPDATE interfaces SET if_index = ?, switchport_mode = 'trunk', vlan_mode = 'trunk',
                               access_vlan = NULL, native_vlan = ?, allowed_vlans = ?, last_seen = ?
                           WHERE id = ?""",
                        (if_index, native_vlan, allowed_vlans, observed_at, interface_id),
                    )
                    inferred_modes += 1
                else:
                    # PVID plus incomplete/ambiguous membership does not prove
                    # access or trunk. Retain prior mode/VLAN configuration.
                    conn.execute(
                        "UPDATE interfaces SET if_index = ?, last_seen = ? WHERE id = ?",
                        (if_index, observed_at, interface_id),
                    )
                updated_interfaces += 1
        conn.commit()
        return {"vlans": vlan_count, "interfaces": updated_interfaces, "mode_inferred": inferred_modes}
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
        # address snapshot from interfaces that disappeared from the IP-bearing
        # inventory. Keep admin_status and oper_status intact because physical
        # and L2 bridge ports are discovered and maintained via SNMP IF-MIB.
        for row in existing_rows:
            if normalize_interface_name(row["interface_name"]) not in current_keys:
                conn.execute(
                    """UPDATE interfaces SET
                           primary_ip = '', ip_address = '', ip_prefix_length = NULL, ip_version = NULL,
                           is_l3 = FALSE, ip_enabled = 0,
                           last_seen = ?
                       WHERE id = ?""",
                    (observed_at, row["id"]),
                )
        for item in interface_rows:
            detected_interface_type = infer_interface_type(item.get("interface_name"))
            interface_ip = item.get("interface_ip") or ""
            ip_version = ipaddress.ip_address(interface_ip).version if interface_ip else None
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
                               admin_status = CASE WHEN ? <> 'unknown' THEN ? ELSE admin_status END,
                               oper_status = CASE WHEN ? <> 'unknown' THEN ? ELSE oper_status END,
                               primary_ip = ?, ip_address = ?, is_l3 = ?,
                               ip_enabled = ?,
                               ip_prefix_length = ?, ip_version = ?,
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
                            item.get("description"),
                            item["admin_status"], item["admin_status"],
                            item["oper_status"], item["oper_status"],
                            interface_ip,
                            interface_ip, l3_enabled, ip_enabled, item.get("prefix_length"), ip_version,
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
                           ip_version, is_l3, ip_enabled, last_seen
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', item['interface_name']).strip('-').lower()}",
                        device["id"], item["interface_name"], item.get("description") or '', item["admin_status"],
                        item["oper_status"], detected_interface_type, default_mode, interface_ip,
                        interface_ip, item.get("prefix_length"), ip_version, l3_enabled, ip_enabled, observed_at,
                    ),
                )
                new_id = f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', item['interface_name']).strip('-').lower()}"
                existing_by_key.setdefault(normalize_interface_name(item["interface_name"]), []).append(new_id)
                updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def _merge_cli_interface_addresses(
    snmp_interfaces: list[dict[str, Any]],
    cli_interfaces: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill missing IP fields from the combined legacy CLI interface category."""
    merged = [dict(item) for item in snmp_interfaces if isinstance(item, dict)]
    by_key = {
        normalize_interface_name(item.get("name")):
        index
        for index, item in enumerate(merged)
        if normalize_interface_name(item.get("name"))
    }
    for record in cli_interfaces:
        if not isinstance(record, dict):
            continue
        interface_name, interface_ip, prefix_length, _admin, _oper = _status_record(record, {})
        key = normalize_interface_name(interface_name)
        if not key or not interface_ip:
            continue
        index = by_key.get(key)
        if index is None:
            continue
        merged[index]["ip_address"] = interface_ip
        if prefix_length is not None:
            merged[index]["prefix_length"] = prefix_length
    return merged


def collect_interface_status_target(
    device_id: str,
    *,
    require_online_network_device: bool = False,
) -> dict[str, Any]:
    """Collect one device's interface status and project it into IPAM Prefixes."""
    device = _load_device(device_id)
    if require_online_network_device and not is_online_network_device_for_interface_collection(device):
        raise RuntimeError("接口采集目标已离线或不再属于网络设备")
    inventory = _load_ip_inventory(device_id)
    from services.collection_plan_service import should_collect

    collect_interfaces = should_collect(device, 'interface_status')
    collect_vlans = should_collect(device, 'vlan')
    if not collect_interfaces and not collect_vlans:
        return {
            'success': True,
            'device_id': device_id,
            'hostname': device.get('hostname') or device_id,
            'skipped': True,
            'skip_reason': 'collection_policy_disabled',
            'interface_count': 0,
            'updated_count': 0,
            'vlan_projection': {'vlans': 0, 'interfaces': 0},
            'prefix_sync': {'ok': True, 'skipped': True},
        }

    domains = _collect_snmp_interface_domains(
        device,
        collect_interfaces=collect_interfaces,
        collect_vlans=collect_vlans,
    )
    snmp_interfaces = domains.get("interfaces") if domains["complete"]["interface_status"] else None
    snmp_addresses = domains.get("addresses") if domains["complete"]["interface_addresses"] else None
    snmp_vlan_data = domains.get("vlan_data") if domains["complete"]["vlan"] else None
    snmp_used = bool(snmp_interfaces)
    snmp_updated = 0
    address_updated = 0
    vlan_projection = {"vlans": 0, "interfaces": 0}

    if snmp_interfaces:
        try:
            snmp_updated = _upsert_snmp_interfaces(device, snmp_interfaces)
        except Exception as exc:
            logger.warning("IF-MIB interface persistence failed for %s (%s)", device_id, type(exc).__name__, exc_info=True)
            domains.setdefault("persisted", {})["interface_status"] = False
        else:
            domains.setdefault("persisted", {})["interface_status"] = True

    if snmp_addresses:
        try:
            address_updated = _upsert_snmp_ip_inventory(device_id, snmp_addresses)
        except Exception as exc:
            # A failed domain write is not an empty snapshot. Keep the previous
            # ip_inventory rows and do not let this failure erase interface IPs.
            logger.warning("IP-MIB snapshot persistence failed for %s (%s)", device_id, type(exc).__name__, exc_info=True)
            domains.setdefault("persisted", {})["interface_addresses"] = False
        else:
            domains.setdefault("persisted", {})["interface_addresses"] = True

    if snmp_vlan_data:
        try:
            vlan_projection = _upsert_qbridge_vlan_data(device_id, snmp_vlan_data)
            domains.setdefault("persisted", {})["vlan"] = True
        except Exception as exc:
            logger.warning("Q-BRIDGE VLAN persistence failed for %s (%s)", device_id, type(exc).__name__, exc_info=True)
            vlan_projection = {"vlans": 0, "interfaces": 0, "error": str(exc)}
            domains.setdefault("persisted", {})["vlan"] = False

    categories: list[str] = []
    if collect_interfaces and (
        not domains["complete"]["interface_status"]
        or not domains["complete"]["interface_addresses"]
    ):
        categories.append("interfaces")
    if collect_interfaces and not domains["complete"]["interface_description"]:
        categories.append("interface_description")
    if collect_vlans and not domains["complete"]["vlan"]:
        categories.append("vlan")

    payload = {"categories": [], "collected_at": _now()}
    cli_collection_error = None
    if categories:
        try:
            payload = collect_read_only_evidence(device, categories=categories, auth_role="auto")
        except Exception as exc:
            cli_collection_error = exc
            logger.info("Targeted interface fallback failed for %s (%s)", device_id, type(exc).__name__)

    cli_interface_category = next(
        (item for item in payload.get("categories", []) if item.get("key") == "interfaces"),
        {},
    )
    cli_interfaces_complete = (
        cli_interface_category.get("success") is True
        and cli_interface_category.get("parse_status") == "matched"
    )
    cli_interface_records = cli_interface_category.get("records") or []
    if collect_interfaces and not domains["complete"]["interface_status"]:
        if not cli_interfaces_complete:
            failure = cli_collection_error or RuntimeError(str(cli_interface_category.get("error") or "接口状态采集失败"))
            message = _friendly_collection_error(failure)
            logger.warning("Interface status collection failed for %s: %s", device.get("hostname") or device_id, message, exc_info=cli_collection_error is not None)
            raise RuntimeError(message) from failure
        category = cli_interface_category
    elif snmp_interfaces:
        # IF-MIB remains the status source when CLI ran only to fill its IP gap.
        category = {
            "key": "interfaces",
            "success": True,
            "parse_status": "matched",
            "records": snmp_interfaces,
            "commands": [],
        }
    else:
        category = cli_interface_category

    if snmp_interfaces and cli_interfaces_complete and not domains["complete"]["interface_addresses"]:
        status_records = _merge_cli_interface_addresses(snmp_interfaces, cli_interface_records)
    else:
        status_records = category.get("records") or []
    description_category = next(
        (item for item in payload.get("categories", []) if item.get("key") == "interface_description"),
        {},
    )
    descriptions = _description_records(description_category) if (
        description_category.get("success") and description_category.get("parse_status") == "matched"
    ) else {}
    vlan_category = next(
        (item for item in payload.get("categories", []) if item.get("key") == "vlan"),
        {},
    )
    if not snmp_vlan_data and vlan_category.get("success") and vlan_category.get("parse_status") == "matched":
        try:
            from services.vlan_discovery_service import project_vlan_records
            vlan_projection = project_vlan_records(device_id, vlan_category.get("records") or [])
        except Exception as vlan_exc:
            logger.warning("VLAN member projection failed for %s: %s", device_id, vlan_exc, exc_info=True)
            vlan_projection = {"vlans": 0, "interfaces": 0, "error": str(vlan_exc)}

    parsed_by_interface, rows = _build_interface_status_rows(
        status_records,
        inventory,
        descriptions,
        snmp_addresses,
        address_snapshot_available=bool(snmp_addresses),
    ) if collect_interfaces else ({}, [])

    updated = _upsert_interfaces(device, rows) if collect_interfaces else 0
    description_updated = 0
    if description_category.get("success") and description_category.get("parse_status") == "matched":
        description_updated = _upsert_interface_descriptions(device_id, descriptions)
    unknown = sum(1 for row in rows if row["admin_status"] == "unknown" or row["oper_status"] == "unknown")
    if should_collect(device, 'prefix_projection'):
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
    else:
        prefix_sync = {"ok": True, "skipped": True, "reason": "collection_policy_disabled"}
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
        "interface_count": len(rows) if rows else (len(snmp_interfaces) if snmp_interfaces else 0),
        "updated_count": updated + snmp_updated,
        "snmp_updated_count": snmp_updated,
        "snmp_address_count": address_updated,
        "snmp_used": snmp_used,
        "snmp_domains": {
            "requested": {"interfaces": collect_interfaces, "vlans": collect_vlans},
            "complete": dict(domains["complete"]),
            "persisted": dict(domains.get("persisted") or {}),
            "errors": dict(domains.get("errors") or {}),
        },
        "description_updated_count": description_updated,
        "vlan_projection": vlan_projection,
        "unknown_status_count": unknown,
        "parsed_count": len(parsed_by_interface),
        "ip_bearing_count": sum(1 for row in rows if row["interface_ip"]),
        "status_only_count": sum(1 for row in rows if not row["interface_ip"]),
        "parser": "snmp" if snmp_used else "textfsm",
        "command": (category.get("commands") or [""])[0],
        "collected_at": payload.get("collected_at") or _now(),
        "prefix_sync": prefix_sync,
        "vlan_sync": vlan_sync,
    }


def _select_interface_collection_devices(device_rows: list[dict[str, Any]]) -> list[str]:
    """Return online device ids with at least one enabled interface/VLAN fact."""
    from services.collection_plan_service import should_collect

    return [
        str(device.get('id')) for device in device_rows
        if device.get('id') and (
            should_collect(device, 'interface_status') or should_collect(device, 'vlan')
        )
    ]


def collect_interface_status_for_online_devices(target_device_ids: set[str] | None = None) -> dict[str, Any]:
    """Refresh CMDB interface status for every online device.

    This is the interface-status phase of the unified Network Reality refresh.
    It also materializes interface skeleton rows for IPs that currently exist
    only in ``ip_inventory``.
    """
    conn = get_db_connection()
    try:
        device_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM devices WHERE status = 'online' ORDER BY hostname, ip_address"
        ).fetchall()]
    finally:
        conn.close()

    if target_device_ids is not None:
        device_rows = [device for device in device_rows if str(device.get('id') or '') in target_device_ids]

    device_ids = _select_interface_collection_devices(device_rows)

    result: dict[str, Any] = {
        'devices': len(device_ids),
        'skipped_by_policy': len(device_rows) - len(device_ids),
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
