"""Collect IP-bearing interface state for the CMDB interface view.

The automation "Interfaces" quick query is the source of truth for the
device-side state.  This worker reuses its command catalog and TextFSM parser,
then joins the parsed state with NSOT's ``ip_inventory`` so only interfaces
with a real address are persisted into the CMDB interface skeleton.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.interface_utils import normalize_interface_name
from services.operational_data_service import collect_operational_data

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
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
            """SELECT ip, interface, type, last_seen
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
                result[key] = {**item, "ip": ip_value}
        return result
    finally:
        conn.close()


def _upsert_interfaces(device: dict[str, Any], interface_rows: list[dict[str, Any]]) -> int:
    if not interface_rows:
        return 0
    conn = get_db_connection()
    try:
        updated = 0
        for item in interface_rows:
            existing = conn.execute(
                """SELECT id FROM interfaces
                   WHERE device_id = ? AND LOWER(TRIM(interface_name)) = LOWER(TRIM(?))
                   LIMIT 1""",
                (device["id"], item["interface_name"]),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE interfaces SET
                           admin_status = ?, oper_status = ?,
                           primary_ip = ?, ip_address = ?, is_l3 = 1,
                           ip_enabled = 1,
                           switchport_mode = COALESCE(NULLIF(switchport_mode, ''), 'routed')
                       WHERE id = ?""",
                    (
                        item["admin_status"], item["oper_status"], item["interface_ip"],
                        item["interface_ip"], existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO interfaces (
                           id, device_id, interface_name, description,
                           admin_status, oper_status, interface_type,
                           switchport_mode, primary_ip, ip_address, is_l3, ip_enabled
                       ) VALUES (?, ?, ?, '', ?, ?, 'physical', 'routed', ?, ?, 1, 1)""",
                    (
                        f"intf-{device['id']}-{re.sub(r'[^a-zA-Z0-9]+', '-', item['interface_name']).strip('-').lower()}",
                        device["id"], item["interface_name"], item["admin_status"],
                        item["oper_status"], item["interface_ip"], item["interface_ip"],
                    ),
                )
            updated += 1
        conn.commit()
        return updated
    finally:
        conn.close()


def collect_interface_status_target(device_id: str) -> dict[str, Any]:
    """Collect one device's Playbook interface status and persist IP rows only."""
    device = _load_device(device_id)
    inventory = _load_ip_inventory(device_id)
    if not inventory:
        return {
            "success": True,
            "device_id": device_id,
            "hostname": device.get("hostname") or device_id,
            "interface_count": 0,
            "message": "设备没有可用的IP接口记录",
        }

    try:
        payload = collect_operational_data(device, categories=["interfaces"], auth_role="auto")
    except Exception as exc:
        message = _friendly_collection_error(exc)
        logger.warning("Interface status collection failed for %s: %s", device.get("hostname") or device_id, message, exc_info=True)
        raise RuntimeError(message) from exc

    category = next((item for item in payload.get("categories", []) if item.get("key") == "interfaces"), {})
    if not category.get("success", False):
        raise RuntimeError(str(category.get("error") or "接口状态采集失败"))

    parsed_by_interface: dict[str, dict[str, str]] = {}
    for record in category.get("records") or []:
        if not isinstance(record, dict):
            continue
        interface_name, parsed_ip, admin_status, oper_status = _status_record(record, {key: value["ip"] for key, value in inventory.items()})
        key = normalize_interface_name(interface_name)
        ip_value = parsed_ip or (inventory.get(key) or {}).get("ip", "")
        if key and ip_value:
            parsed_by_interface[key] = {
                "interface_name": interface_name,
                "interface_ip": ip_value,
                "admin_status": admin_status,
                "oper_status": oper_status,
            }

    # NSOT owns the complete IP list.  Keep every IP-bearing interface in the
    # result, even when a vendor parser omitted a row; that row remains clearly
    # marked unknown until the next successful status collection.
    rows = []
    for key, item in inventory.items():
        parsed = parsed_by_interface.get(key, {})
        rows.append({
            "interface_name": parsed.get("interface_name") or item.get("interface") or key,
            "interface_ip": item["ip"],
            "admin_status": parsed.get("admin_status") or "unknown",
            "oper_status": parsed.get("oper_status") or "unknown",
        })

    updated = _upsert_interfaces(device, rows)
    unknown = sum(1 for row in rows if row["admin_status"] == "unknown" or row["oper_status"] == "unknown")
    return {
        "success": True,
        "device_id": device_id,
        "hostname": device.get("hostname") or device_id,
        "interface_count": len(rows),
        "updated_count": updated,
        "unknown_status_count": unknown,
        "parsed_count": len(parsed_by_interface),
        "parser": category.get("parser") or "textfsm",
        "command": (category.get("commands") or [""])[0],
        "collected_at": payload.get("collected_at") or _now(),
    }
