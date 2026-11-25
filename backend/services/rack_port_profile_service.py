"""Zero-polling-overhead real physical port & SNMP hardware sensor aggregator for 3D Racks.

Reads directly from already-collected local PostgreSQL tables:
  - ``interfaces`` (physical port inventory, oper_status, speed, description)
  - ``interface_telemetry_1m`` (1-minute SNMP IF-MIB traffic & error rollups)
  - ``snmp_hardware_sensors`` (ENTITY-MIB PSU / Fan / Temperature health)

Never issues any SNMP/SSH request to network devices.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from typing import Any

from services import rack_asset_resolver

logger = logging.getLogger(__name__)

_VIRTUAL_PREFIXES = (
    "vlan",
    "loopback",
    "inloop",
    "null",
    "bridge-aggregation",
    "route-aggregation",
    "eth-trunk",
    "port-channel",
    "po",
    "tunnel",
    "m-eth",
    "m-gigabit",
    "m-ge",
    "management",
    "mgmt",
    "meth",
    "aux",
    "console",
    "register",
    "smart",
    "sslvpn",
    "dialer",
    "virtual",
    "bvi",
    "nve",
    "lo",
    "veth",
    "docker",
    "br-",
)

_THREE_TUPLE_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)$")
_TWO_TUPLE_RE = re.compile(r"(\d+)\s*/\s*(\d+)$")
_TRAILING_NUM_RE = re.compile(r"(\d+)$")


def _is_virtual_interface(name: str) -> bool:
    low = str(name or "").strip().lower()
    if not low:
        return True
    if any(low.startswith(prefix) for prefix in _VIRTUAL_PREFIXES):
        return True
    # Skip subinterfaces like GigabitEthernet1/0/1.100
    if "." in low:
        return True
    return False


def _short_interface_name(name: str) -> str:
    value = str(name or "").strip()
    replacements = (
        (r"^Ten-GigabitEthernet", "10GE"),
        (r"^TwentyFiveGigE", "25GE"),
        (r"^FortyGigE", "40GE"),
        (r"^HundredGigE", "100GE"),
        (r"^FourHundredGigE", "400GE"),
        (r"^XGigabitEthernet", "10GE"),
        (r"^GigabitEthernet", "GE"),
        (r"^FastEthernet", "FE"),
        (r"^Ethernet", "Eth"),
    )
    for pattern, repl in replacements:
        updated = re.sub(pattern, repl, value, flags=re.IGNORECASE)
        if updated != value:
            return updated
    return value


def _parse_slot_subslot_port(name: str) -> tuple[int, int, int]:
    cleaned = str(name or "").strip()
    m3 = _THREE_TUPLE_RE.search(cleaned)
    if m3:
        return int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
    m2 = _TWO_TUPLE_RE.search(cleaned)
    if m2:
        return int(m2.group(1)), 0, int(m2.group(2))
    m1 = _TRAILING_NUM_RE.search(cleaned)
    return 1, 0, int(m1.group(1)) if m1 else 0


def _parse_speed_mbps(raw_speed: Any, name: str) -> int:
    text = str(raw_speed or "").strip().lower()
    if text:
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        if m:
            num = float(m.group(1))
            if "gbps" in text or text.endswith("g"):
                return int(round(num * 1000))
            if "kbps" in text or text.endswith("k"):
                return max(1, int(round(num / 1000)))
            if num >= 1_000_000:
                return int(round(num / 1_000_000))
            return int(round(num))
    low = name.lower()
    if re.search(r"(?:400g|fourhundred)", low):
        return 400_000
    if re.search(r"(?:100g|hundredgig|hge)", low):
        return 100_000
    if re.search(r"(?:40g|fortygig|fge)", low):
        return 40_000
    if re.search(r"(?:25g|twentyfive)", low):
        return 25_000
    if re.search(r"(?:10g|ten-?gig|xge|sfp\+)", low):
        return 10_000
    if re.search(r"(?:ge|gigabit)", low):
        return 1_000
    return 0


def _classify_port_type(name: str, speed_mbps: int, is_optical_dc: bool) -> str:
    low = name.lower()
    if re.search(r"(?:qsfp|fge|hge|40g|100g|400g|fortygig|hundredgig)", low) or speed_mbps >= 40_000:
        return "qsfp"
    if re.search(r"(?:sfp|xge|10g|25g|ten-?gig|twentyfive)", low) or speed_mbps >= 10_000 or is_optical_dc:
        return "sfp"
    return "rj45"


def _is_up_status(value: Any) -> bool:
    return str(value or "").strip().lower() in {"up", "active", "normal", "1", "true", "online"}


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _fetch_latest_telemetry_1m(conn, device_ids: list[str]) -> dict[tuple[str, str], dict[str, Any]]:
    if not device_ids:
        return {}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        # Use idx_interface_telemetry_1m_ts (O(log N) backwards index scan) to
        # bound the window to the latest 2 hours of samples instead of seq-scanning
        # the full multi-week/month interface_telemetry_1m table.
        max_row = conn.execute("SELECT MAX(ts_minute) AS max_ts FROM interface_telemetry_1m").fetchone()
        max_ts_raw = _row_to_dict(max_row).get("max_ts") if max_row else None
        if not max_ts_raw:
            return result

        cutoff_ts: Any = None
        if isinstance(max_ts_raw, datetime):
            cutoff_ts = max_ts_raw - timedelta(hours=2)
        else:
            try:
                parsed = datetime.fromisoformat(str(max_ts_raw).strip().replace("Z", "+00:00"))
                cutoff_ts = (parsed - timedelta(hours=2)).isoformat()
            except ValueError:
                cutoff_ts = None

        placeholders = ",".join(["?"] * len(device_ids))
        if cutoff_ts is not None:
            sql = (
                "SELECT DISTINCT ON (device_id, interface_name) "
                "device_id, interface_name, ts_minute, avg_in_bps, avg_out_bps, err_delta_sum "
                f"FROM interface_telemetry_1m WHERE ts_minute >= ? AND device_id IN ({placeholders}) "
                "ORDER BY device_id, interface_name, ts_minute DESC"
            )
            params: tuple[Any, ...] = (cutoff_ts, *device_ids)
        else:
            sql = (
                "SELECT DISTINCT ON (device_id, interface_name) "
                "device_id, interface_name, ts_minute, avg_in_bps, avg_out_bps, err_delta_sum "
                f"FROM interface_telemetry_1m WHERE device_id IN ({placeholders}) "
                "ORDER BY device_id, interface_name, ts_minute DESC"
            )
            params = tuple(device_ids)

        rows = conn.execute(sql, params).fetchall()
        for raw in rows:
            row = _row_to_dict(raw)
            did = str(row.get("device_id") or "")
            iname = str(row.get("interface_name") or "").strip().lower()
            if did and iname:
                result[(did, iname)] = row
    except Exception as exc:
        logger.debug("Optional interface_telemetry_1m lookup skipped: %s", exc)
    return result


def _fetch_hardware_sensor_summary(conn, device_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not device_ids:
        return {}
    placeholders = ",".join(["?"] * len(device_ids))
    # Use exact indexable component_class equality so PostgreSQL uses
    # idx_snmp_hw_sensors_device_class_state (device_id, component_class, ...)
    # instead of scanning thousands of optical/DOM/voltage/current/watt rows.
    sql = (
        "SELECT device_id, component_class, "
        "COUNT(*) AS sensor_count, "
        "MAX(CASE WHEN component_class = 'temperature' "
        "AND last_value > 0 AND last_value < 120 THEN last_value END) AS max_temp_c, "
        "SUM(CASE WHEN LOWER(COALESCE(last_quality, '')) IN ('bad', 'critical', 'fault', 'alarm') "
        "THEN 1 ELSE 0 END) AS fault_count "
        f"FROM snmp_hardware_sensors WHERE device_id IN ({placeholders}) "
        "AND component_class IN ('temperature', 'power_supply_state', 'fan_state', 'power_supply', 'psu', 'fan') "
        "GROUP BY device_id, component_class"
    )
    summary: dict[str, dict[str, Any]] = {}
    try:
        rows = conn.execute(sql, tuple(device_ids)).fetchall()
        for raw in rows:
            row = _row_to_dict(raw)
            did = str(row.get("device_id") or "")
            if not did:
                continue
            bucket = summary.setdefault(
                did,
                {"psu_status": "unknown", "fan_status": "unknown", "temperature_c": None, "sensor_count": 0},
            )
            bucket["sensor_count"] += int(row.get("sensor_count") or 0)
            cls = str(row.get("component_class") or "").lower()
            fault_count = int(row.get("fault_count") or 0)
            max_temp = row.get("max_temp_c")
            if "temp" in cls and max_temp is not None:
                try:
                    tval = float(max_temp)
                    if 0 < tval < 120:
                        prev = bucket["temperature_c"]
                        bucket["temperature_c"] = round(max(prev, tval) if prev is not None else tval, 1)
                except (TypeError, ValueError):
                    pass
            elif "power_supply" in cls or "psu" in cls:
                if fault_count > 0:
                    bucket["psu_status"] = "fault"
                elif bucket["psu_status"] != "fault":
                    bucket["psu_status"] = "ok"
            elif "fan" in cls:
                if fault_count > 0:
                    bucket["fan_status"] = "fault"
                elif bucket["fan_status"] != "fault":
                    bucket["fan_status"] = "ok"
    except Exception as exc:
        logger.debug("Optional snmp_hardware_sensors lookup skipped: %s", exc)
    return summary


def enrich_rack_devices_with_port_profiles(conn, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach zero-polling-overhead real physical port profiles to rack devices in bulk."""
    if not devices:
        return devices

    device_id_map: dict[str, list[dict[str, Any]]] = {}
    for dev in devices:
        ndid = str(dev.get("network_device_id") or "").strip()
        if ndid:
            device_id_map.setdefault(ndid, []).append(dev)

    if not device_id_map:
        return devices

    device_ids = list(device_id_map.keys())
    placeholders = ",".join(["?"] * len(device_ids))
    rows_by_device: dict[str, list[dict[str, Any]]] = {}
    try:
        sql = (
            "SELECT device_id, interface_name, oper_status, admin_status, speed, description, "
            "last_observed_at, status_observed_at "
            f"FROM interfaces WHERE device_id IN ({placeholders})"
        )
        for raw in conn.execute(sql, tuple(device_ids)).fetchall():
            row = _row_to_dict(raw)
            did = str(row.get("device_id") or "")
            if did:
                rows_by_device.setdefault(did, []).append(row)
    except Exception as exc:
        logger.warning("Failed to load CMDB interfaces for rack devices: %s", exc)
        return devices

    telemetry_map = _fetch_latest_telemetry_1m(conn, device_ids)
    sensor_map = _fetch_hardware_sensor_summary(conn, device_ids)

    for ndid, dev_list in device_id_map.items():
        raw_ifaces = rows_by_device.get(ndid, [])
        if not raw_ifaces:
            continue

        sample_dev = dev_list[0]
        dev_identity = f"{sample_dev.get('vendor') or ''} {sample_dev.get('model') or ''} {sample_dev.get('resolved_asset_key') or ''}".lower()
        is_optical_dc = any(tok in dev_identity for tok in ("s6850", "s6800", "ce68", "s6730", "s6510", "nexus", "93180"))

        # Deduplicate aliases such as GE1/0/1 vs GigabitEthernet1/0/1 by (slot, subslot, port, port_type)
        dedup: dict[tuple[int, int, int, str], dict[str, Any]] = {}
        latest_ts_candidates: list[str] = []

        for row in raw_ifaces:
            iface_name = str(row.get("interface_name") or "").strip()
            if _is_virtual_interface(iface_name):
                continue
            slot, subslot, port_num = _parse_slot_subslot_port(iface_name)
            speed_mbps = _parse_speed_mbps(row.get("speed"), iface_name)
            port_type = _classify_port_type(iface_name, speed_mbps, is_optical_dc)
            is_up = _is_up_status(row.get("oper_status"))
            short_name = _short_interface_name(iface_name)

            telem = telemetry_map.get((ndid, iface_name.lower())) or telemetry_map.get((ndid, short_name.lower()))
            in_bps = int(round(float(telem.get("avg_in_bps") or 0))) if telem else 0
            out_bps = int(round(float(telem.get("avg_out_bps") or 0))) if telem else 0
            err_sum = int(round(float(telem.get("err_delta_sum") or 0))) if telem else 0
            ts_str = str(
                (telem.get("ts_minute") if telem else None)
                or row.get("status_observed_at")
                or row.get("last_observed_at")
                or ""
            ).strip()
            if ts_str:
                latest_ts_candidates.append(ts_str)

            entry = {
                "name": iface_name,
                "short_name": short_name,
                "slot": slot,
                "subslot": subslot,
                "port": port_num,
                "port_type": port_type,
                "speed_mbps": speed_mbps,
                "oper_status": "up" if is_up else "down",
                "admin_status": str(row.get("admin_status") or "").strip().lower() or "unknown",
                "in_bps": in_bps,
                "out_bps": out_bps,
                "errors": err_sum,
                "description": str(row.get("description") or "").strip(),
            }
            dedup_key = (slot, subslot, port_num, port_type)
            prev = dedup.get(dedup_key)
            if prev is None:
                dedup[dedup_key] = entry
            else:
                # Prefer longer canonical interface name & UP/telemetry evidence
                prefer_new = (
                    (entry["oper_status"] == "up" and prev["oper_status"] != "up")
                    or (len(entry["name"]) > len(prev["name"]) and entry["oper_status"] == prev["oper_status"])
                    or (entry["in_bps"] + entry["out_bps"] > prev["in_bps"] + prev["out_bps"])
                )
                if prefer_new:
                    if not entry["description"] and prev["description"]:
                        entry["description"] = prev["description"]
                    dedup[dedup_key] = entry

        ports = sorted(dedup.values(), key=lambda p: (p["slot"], p["subslot"], p["port"], p["name"]))
        if not ports:
            continue

        # Aggregate slot summaries (drives box port counts AND modular chassis slot cards!)
        slot_buckets: dict[int, dict[str, Any]] = {}
        for p in ports:
            sb = slot_buckets.setdefault(
                p["slot"],
                {
                    "slot": p["slot"],
                    "total_ports": 0,
                    "up_count": 0,
                    "rj45_count": 0,
                    "sfp_count": 0,
                    "qsfp_count": 0,
                    "min_port": p["port"],
                    "max_port": p["port"],
                },
            )
            sb["total_ports"] += 1
            if p["oper_status"] == "up":
                sb["up_count"] += 1
            sb[f"{p['port_type']}_count"] += 1
            sb["min_port"] = min(sb["min_port"], p["port"])
            sb["max_port"] = max(sb["max_port"], p["port"])

        slots = [slot_buckets[k] for k in sorted(slot_buckets.keys())]
        up_count = sum(1 for p in ports if p["oper_status"] == "up")
        profile = {
            "source": "CMDB+SNMP",
            "total_ports": len(ports),
            "up_count": up_count,
            "down_count": len(ports) - up_count,
            "sampled_at": max(latest_ts_candidates) if latest_ts_candidates else None,
            "slots": slots,
            "hardware_sensors": sensor_map.get(ndid),
            "ports": ports,
        }

        for dev in dev_list:
            dev["physical_port_profile"] = profile
            # Refine generic 24p/48p asset choice if device fell back to global_generic switch
            if (
                dev.get("asset_resolution_level") == "global_generic"
                and str(dev.get("resolved_asset_key") or "").startswith("generic_switch_1u")
            ):
                hint_model = "24p" if len(ports) <= 28 else "48p"
                refined = rack_asset_resolver.resolve_asset(
                    vendor=str(dev.get("vendor") or ""),
                    model=hint_model,
                    device_type=str(dev.get("device_role") or "switch"),
                    height_u=dev.get("height_u") or dev.get("u_height"),
                )
                if refined.get("available"):
                    dev["resolved_asset_key"] = refined["asset_key"]
                    dev["asset_url"] = refined["asset_url"]
                    dev["asset_path"] = refined["glb_path"]

    return devices
