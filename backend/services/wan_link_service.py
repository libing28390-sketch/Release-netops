"""P0 internet egress link monitoring service.

This service deliberately reuses the existing IF-MIB collector.  It stores
raw counters and derived values together so a failed SNMP poll never turns a
valid previous rate into a misleading zero.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database import _USE_PG, get_db_connection
from services.snmp_counter_service import calculate_counter_delta
from services.snmp_metric_profile_service import resolve_metric_profiles
from services.snmp_service import collect_interface_data_detailed
from services.vault_service import resolve_collector_credentials


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _num(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _bps(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else max(0, int(round(number)))


def _apply_contract_utilization(item: dict[str, Any]) -> dict[str, Any]:
    """Calculate utilization from the displayed rate and current contract."""
    for direction in ("download", "upload"):
        rate = _num(item.get(f"{direction}_bps"))
        contract = _num(item.get(f"contracted_{direction}_bps"))
        item[f"{direction}_util_pct"] = round(rate * 100 / contract, 3) if rate is not None and contract and contract > 0 else None
    return item


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _sample_table() -> str:
    return "wan_link_samples_1m_partitioned" if _USE_PG else "wan_link_samples_1m"


def _required_samples(duration_sec: int, interval_sec: int) -> int:
    return max(1, math.ceil(max(0, duration_sec) / max(1, interval_sec)))


_WAN_DEVICE_ROLES = ("core", "edge", "border", "gateway", "router", "firewall", "sd-wan")
_WAN_DEVICE_CATEGORIES = ("router", "firewall", "gateway", "edge", "security-gateway", "sd-wan")


def _normalize_interface_name(value: Any) -> str:
    """Normalize common vendor aliases so Et0/0 and Ethernet0/0 deduplicate."""
    name = re.sub(r"[\s_-]+", "", str(value or "").strip().lower())
    for prefix in (
        "hundredgigabitethernet", "tengigabitethernet", "gigabitethernet",
        "fastethernet", "ethernet", "loopback", "portchannel",
    ):
        if name.startswith(prefix):
            return {"hundredgigabitethernet": "hu", "tengigabitethernet": "te", "gigabitethernet": "gi", "fastethernet": "fa", "ethernet": "et", "loopback": "lo", "portchannel": "po"}[prefix] + name[len(prefix):]
    return name


def _deduplicate_interface_options(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("device_id") or ""), _normalize_interface_name(row.get("interface_name")))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _interface_status(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "unknown").lower()
    return "up" if status in {"up", "1", "operup"} else "down" if status in {"down", "2", "operdown"} else "unknown"


def _directional_counters(link: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Apply the configured logical direction without changing raw evidence."""
    if str(link.get("direction_mode") or "normal") == "reversed":
        return {
            "in_octets": current.get("out_octets"),
            "out_octets": current.get("in_octets"),
            "in_octets_hc": current.get("out_octets_hc"),
            "out_octets_hc": current.get("in_octets_hc"),
            "in_octets_32": current.get("out_octets_32"),
            "out_octets_32": current.get("in_octets_32"),
        }
    return current


def _match_interface(link: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted_index = str(link.get("if_index") or "").strip()
    wanted_name = str(link.get("interface_name") or "").strip().lower()
    for item in items:
        if wanted_index and str(item.get("if_index") or "") == wanted_index:
            return item
    for item in items:
        if str(item.get("name") or "").strip().lower() == wanted_name:
            return item
    return None


def _calculate_rates(link: dict[str, Any], current: dict[str, Any], previous: dict[str, Any] | None, sampled_at: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    flags: dict[str, Any] = {}
    if not previous or str(previous.get("collection_status")) != "success":
        flags["baseline"] = True
        return {"download_bps": None, "upload_bps": None, "download_util_pct": None, "upload_util_pct": None}, flags

    elapsed = (sampled_at - datetime.fromisoformat(str(previous["sampled_at"]).replace("Z", "+00:00"))).total_seconds()
    if elapsed < 10 or elapsed > max(600, int(link.get("collection_interval_sec") or 60) * 3):
        flags["interval_abnormal"] = True
        return {"download_bps": None, "upload_bps": None, "download_util_pct": None, "upload_util_pct": None}, flags

    values: dict[str, Any] = {}
    current = _directional_counters(link, current)
    previous = _directional_counters(link, previous)
    counter_width = int(current.get("counter_width") or previous.get("counter_width") or 64)
    for direction, column in (("download", "in_octets"), ("upload", "out_octets")):
        now_counter = _num(current.get(column))
        old_counter = _num(previous.get(column))
        if now_counter is None or old_counter is None:
            flags[f"{direction}_counter_missing"] = True
            values[f"{direction}_bps"] = None
            values[f"{direction}_util_pct"] = None
            continue
        if counter_width not in (32, 64):
            flags[f"{direction}_counter_width_unknown"] = True
            values[f"{direction}_bps"] = None
            values[f"{direction}_util_pct"] = None
            continue
        speed_bps = max(0.0, (_num(current.get("speed_mbps")) or 0.0) * 1_000_000)
        delta_result = calculate_counter_delta(
            now_counter,
            old_counter,
            elapsed,
            counter_width,
            # WAN telemetry keeps measured rates above the reported IF-MIB
            # speed and records that mismatch below as a quality flag.  A
            # stale/virtual speed must not erase otherwise valid counters.
            max_rate_per_sec=None,
            current_uptime_cs=int(_num(current.get("device_uptime_cs")) or 0) or None,
            previous_uptime_cs=int(_num(previous.get("device_uptime_cs")) or 0) or None,
        )
        counter_status = str(delta_result.get("status") or "invalid")
        if counter_status == "wrapped":
            flags[f"{direction}_counter_wrap"] = True
        elif counter_status in {"ambiguous_wrap_or_reset", "device_restart"}:
            # Keep the WAN contract stable: a reset/reboot is a quality flag,
            # never a synthetic zero-rate sample.  The shared counter helper
            # uses a more precise status internally, while the WAN API has
            # historically exposed the compact *_counter_reset key.
            flags[f"{direction}_counter_reset"] = True
            values[f"{direction}_bps"] = None
            values[f"{direction}_util_pct"] = None
            continue
        elif counter_status != "ok":
            flags[f"{direction}_counter_{counter_status}"] = True
            values[f"{direction}_bps"] = None
            values[f"{direction}_util_pct"] = None
            continue
        rate = int(round(float(delta_result["rate_per_sec"]) * 8))
        physical_bps = max(0, int(round(_num(current.get("speed_mbps")) or 0)) * 1_000_000)
        if physical_bps and rate > physical_bps * 1.2:
            # A live interface can legitimately report more traffic than the
            # nominal speed stored in IF-MIB (for example, stale speed data,
            # virtual lab links, or a contracted rate that differs from the
            # port's reported speed). Keep the measured rate so the WAN page
            # remains useful; expose the mismatch as quality evidence instead
            # of turning a successful counter delta into a blank sample.
            flags[f"{direction}_over_interface_speed"] = True
        contracted = _bps(link.get(f"contracted_{direction}_bps")) or 0
        values[f"{direction}_bps"] = rate
        values[f"{direction}_util_pct"] = round(rate / contracted * 100, 3) if contracted else None
    return values, flags


def _ensure_alert_rules(conn, link: dict[str, Any], now: str) -> None:
    defaults = [
        ("interface_down", "critical", None, 180, None, 120),
        ("util_70", "info", 70, 600, 60, 300),
        ("util_85", "warning", 85, 300, 70, 300),
        ("util_95", "critical", 95, 120, 85, 300),
    ]
    for metric, severity, threshold, duration, recovery, recovery_duration in defaults:
        conn.execute(
            """INSERT INTO wan_alert_rules
                (id, link_id, metric, severity, threshold_value, duration_sec,
                 recovery_threshold, recovery_duration_sec, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?)
               ON CONFLICT(link_id, metric) DO NOTHING""",
            (f"wan-rule-{uuid.uuid4().hex}", link["id"], metric, severity, threshold, duration, recovery, recovery_duration, now, now),
        )


def _sample_value(sample: dict[str, Any], metric: str) -> float | bool | None:
    if metric == "interface_down":
        return str(sample.get("oper_status") or "unknown") != "up" and str(sample.get("collection_status")) == "success"
    if metric.startswith("util_"):
        download = _num(sample.get("download_util_pct"))
        upload = _num(sample.get("upload_util_pct"))
        values = [value for value in (download, upload) if value is not None]
        return max(values) if values else None
    return None


def _evaluate_alerts(conn, link: dict[str, Any], now: str) -> int:
    rules = conn.execute("SELECT * FROM wan_alert_rules WHERE link_id = ? AND enabled = TRUE", (link["id"],)).fetchall()
    samples = [dict(row) for row in conn.execute(
        f"SELECT * FROM {_sample_table()} WHERE link_id = ? ORDER BY sampled_at DESC LIMIT 80", (link["id"],)
    ).fetchall()]
    active_count = 0
    interval = int(link.get("collection_interval_sec") or 60)
    from services.wan_p1_service import is_wan_link_in_maintenance
    in_maintenance = is_wan_link_in_maintenance(conn, str(link["id"]), str(link.get("site_id") or ""), now)
    for rule_row in rules:
        rule = dict(rule_row)
        metric = str(rule["metric"])
        trigger_value = _num(rule.get("threshold_value"))
        recovery_value = _num(rule.get("recovery_threshold"))
        triggered = 0
        recovered = 0
        for sample in samples:
            value = _sample_value(sample, metric)
            if isinstance(value, bool):
                is_triggered = value
                is_recovered = not value
            elif value is None:
                is_triggered = False
                is_recovered = False
            else:
                is_triggered = trigger_value is not None and value >= trigger_value
                is_recovered = recovery_value is not None and value <= recovery_value
            if is_triggered:
                triggered += 1
            else:
                break
        for sample in samples:
            value = _sample_value(sample, metric)
            if isinstance(value, bool):
                is_recovered = not value
            elif value is None:
                is_recovered = False
            else:
                is_recovered = recovery_value is not None and value <= recovery_value
            if is_recovered:
                recovered += 1
            else:
                break

        event = conn.execute(
            "SELECT * FROM wan_alert_events WHERE link_id = ? AND metric = ? AND status = 'firing' ORDER BY started_at DESC LIMIT 1",
            (link["id"], metric),
        ).fetchone()
        event_dict = _row_dict(event)
        if in_maintenance:
            if event_dict and event_dict.get("status") == "firing":
                conn.execute("UPDATE wan_alert_events SET details = ?, updated_at = ? WHERE id = ?", (json.dumps({"suppressed": True, "reason": "maintenance_window"}), now, event_dict["id"]))
            continue
        if event_dict and event_dict.get("status") == "firing":
            if recovered >= _required_samples(int(rule["recovery_duration_sec"]), interval):
                conn.execute(
                    "UPDATE wan_alert_events SET status = 'resolved', recovered_at = ?, last_seen_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, now, event_dict["id"]),
                )
            else:
                latest = samples[0] if samples else {}
                current_value = _sample_value(latest, metric)
                conn.execute("UPDATE wan_alert_events SET last_seen_at = ?, metric_value = ?, updated_at = ? WHERE id = ?", (now, current_value if not isinstance(current_value, bool) else None, now, event_dict["id"]))
                active_count += 1
        elif triggered >= _required_samples(int(rule["duration_sec"]), interval):
            latest = samples[0] if samples else {}
            current_value = _sample_value(latest, metric)
            title = "接口 Down" if metric == "interface_down" else f"出口带宽利用率达到 {int(trigger_value or 0)}%"
            direction = ""
            if metric.startswith("util_"):
                down = _num(latest.get("download_util_pct"))
                up = _num(latest.get("upload_util_pct"))
                direction = "download" if (down or 0) >= (up or 0) else "upload"
            event_key = f"wan:{link['id']}:{metric}:{uuid.uuid4().hex}"
            conn.execute(
                """INSERT INTO wan_alert_events
                    (id, event_key, link_id, metric, severity, status, title, message,
                     metric_value, threshold_value, direction, started_at, last_seen_at, details, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'firing', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"wan-event-{uuid.uuid4().hex}", event_key, link["id"], metric, rule["severity"], title,
                 "达到持续时间阈值，已生成出口链路告警", current_value if not isinstance(current_value, bool) else None,
                 trigger_value, direction, now, now, json.dumps({"duration_sec": rule["duration_sec"], "recovery_duration_sec": rule["recovery_duration_sec"]}), now, now),
            )
            active_count += 1
    return active_count


async def _collect_link(link: dict[str, Any], collected: dict[str, Any] | None = None, sampled_dt: datetime | None = None) -> dict[str, Any]:
    started = time.monotonic()
    sampled_dt = (sampled_dt or _now()).replace(second=0, microsecond=0)
    sampled_at = _iso(sampled_dt)
    conn = get_db_connection()
    try:
        _ensure_alert_rules(conn, link, sampled_at)
        device_row = conn.execute("SELECT * FROM devices WHERE id = ?", (link["device_id"],)).fetchone()
        device = _row_dict(device_row) or {}
        credential = resolve_collector_credentials(device)
        snmp = credential.get("snmp") or {}
        snmp_ip = str(snmp.get("server") or device.get("ip_address") or "").strip()
        community = str(snmp.get("community") or "").strip()
        port = int(snmp.get("port") or device.get("snmp_port") or 161)
        interface_config = resolve_metric_profiles(device).get('interface') or None
        previous_row = conn.execute(f"SELECT * FROM {_sample_table()} WHERE link_id = ? ORDER BY sampled_at DESC LIMIT 1", (link["id"],)).fetchone()
        previous = _row_dict(previous_row)
        item: dict[str, Any] | None = None
        collection_status = "success"
        quality_flags: dict[str, Any] = {}
        if not snmp_ip or not community:
            collection_status = "not_configured"
            quality_flags["reason"] = "SNMP credentials are not configured"
        else:
            detail = collected
            if detail is None:
                detail = await collect_interface_data_detailed(
                    snmp_ip,
                    community,
                    port,
                    interface_config,
                )
            collection_status = str(detail.get("status") or "timeout")
            items = detail.get("items") or []
            item = _match_interface(link, items)
            if collection_status == "success" and not item:
                collection_status = "interface_not_found"
                quality_flags["reason"] = "Configured interface was not returned by IF-MIB"
            if detail.get("error_code"):
                quality_flags["error_code"] = detail.get("error_code")
            if detail.get("error_message"):
                quality_flags["error_message"] = detail.get("error_message")

        current: dict[str, Any] = {
            "in_octets": item.get("in_octets") if item else None,
            "out_octets": item.get("out_octets") if item else None,
            "speed_mbps": item.get("speed_mbps") if item else None,
            "in_errors": item.get("in_errors") if item else None,
            "out_errors": item.get("out_errors") if item else None,
            "in_discards": item.get("in_discards") if item else None,
            "out_discards": item.get("out_discards") if item else None,
            "in_octets_hc": item.get("in_octets_hc") if item else None,
            "out_octets_hc": item.get("out_octets_hc") if item else None,
            "in_octets_32": item.get("in_octets_32") if item else None,
            "out_octets_32": item.get("out_octets_32") if item else None,
            "counter_width": item.get("counter_width") if item else None,
            "counter_source": item.get("counter_source") if item else "unknown",
            "counter_quality": item.get("counter_quality") if item else "unknown",
            "admin_status": item.get("admin_status") if item else "unknown",
            "oper_status": item.get("status") if item else "unknown",
            "device_uptime_cs": item.get("device_uptime_cs") if item else None,
        }
        status = _interface_status(item or {})
        derived: dict[str, Any] = {"download_bps": None, "upload_bps": None, "download_util_pct": None, "upload_util_pct": None}
        if collection_status == "success":
            derived, rate_flags = _calculate_rates(link, current, previous, sampled_dt)
            quality_flags.update(rate_flags)
        else:
            status = "unknown"

        error_deltas: dict[str, Any] = {}
        delta_names = {
            "in_errors": "in_error_delta",
            "out_errors": "out_error_delta",
            "in_discards": "in_discard_delta",
            "out_discards": "out_discard_delta",
        }
        for key, delta_name in delta_names.items():
            now_counter = _num(current.get(key))
            old_counter = _num(previous.get(key)) if previous else None
            error_deltas[delta_name] = int(now_counter - old_counter) if now_counter is not None and old_counter is not None and now_counter >= old_counter else None

        values = (
            f"""INSERT INTO wan_link_samples_1m
                (id, link_id, sampled_at, in_octets, out_octets, download_bps, upload_bps,
                 download_util_pct, upload_util_pct, in_error_delta, out_error_delta,
                 in_discard_delta, out_discard_delta, admin_status, oper_status,
                 collection_status, quality_flags, collection_latency_ms, created_at,
                 in_octets_hc, out_octets_hc, in_octets_32, out_octets_32, counter_width,
                 counter_source, counter_quality)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(link_id, sampled_at) DO UPDATE SET
                 in_octets = excluded.in_octets, out_octets = excluded.out_octets,
                 download_bps = excluded.download_bps, upload_bps = excluded.upload_bps,
                 download_util_pct = excluded.download_util_pct, upload_util_pct = excluded.upload_util_pct,
                 in_error_delta = excluded.in_error_delta, out_error_delta = excluded.out_error_delta,
                 in_discard_delta = excluded.in_discard_delta, out_discard_delta = excluded.out_discard_delta,
                 admin_status = excluded.admin_status, oper_status = excluded.oper_status,
                 collection_status = excluded.collection_status, quality_flags = excluded.quality_flags,
                 collection_latency_ms = excluded.collection_latency_ms,
                 in_octets_hc = excluded.in_octets_hc, out_octets_hc = excluded.out_octets_hc,
                 in_octets_32 = excluded.in_octets_32, out_octets_32 = excluded.out_octets_32,
                 counter_width = excluded.counter_width, counter_source = excluded.counter_source,
                 counter_quality = excluded.counter_quality""",
            (f"wan-sample-{uuid.uuid4().hex}", link["id"], sampled_at, _bps(current.get("in_octets")), _bps(current.get("out_octets")),
             derived["download_bps"], derived["upload_bps"], derived["download_util_pct"], derived["upload_util_pct"],
             error_deltas["in_error_delta"], error_deltas["out_error_delta"], error_deltas["in_discard_delta"], error_deltas["out_discard_delta"],
              current.get("admin_status") or "unknown", current.get("oper_status") or "unknown", collection_status, json.dumps(quality_flags), int((time.monotonic() - started) * 1000), sampled_at,
             _bps(current.get("in_octets_hc")), _bps(current.get("out_octets_hc")), _bps(current.get("in_octets_32")), _bps(current.get("out_octets_32")), current.get("counter_width"), current.get("counter_source"), current.get("counter_quality")),
        )
        values = (values[0].replace("INSERT INTO wan_link_samples_1m", f"INSERT INTO {_sample_table()}"), values[1])
        conn.execute(*values)
        active_alerts = _evaluate_alerts(conn, link, sampled_at)
        previous_current_row = conn.execute(
            "SELECT consecutive_down_count FROM wan_link_current_status WHERE link_id = ?",
            (link["id"],),
        ).fetchone()
        previous_down_count = int((dict(previous_current_row).get("consecutive_down_count") or 0) if previous_current_row else 0)
        health = "unknown" if collection_status != "success" else "unavailable" if status == "down" else "critical" if max(_num(derived.get("download_util_pct")) or 0, _num(derived.get("upload_util_pct")) or 0) >= 95 else "degraded" if max(_num(derived.get("download_util_pct")) or 0, _num(derived.get("upload_util_pct")) or 0) >= 85 else "healthy"
        conn.execute(
            """INSERT INTO wan_link_current_status
                (link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct,
                 admin_status, oper_status, collection_status, health_status, active_alert_count,
                 last_success_at, consecutive_down_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(link_id) DO UPDATE SET
                 sampled_at = excluded.sampled_at,
                 download_bps = COALESCE(excluded.download_bps, wan_link_current_status.download_bps),
                 upload_bps = COALESCE(excluded.upload_bps, wan_link_current_status.upload_bps),
                 download_util_pct = COALESCE(excluded.download_util_pct, wan_link_current_status.download_util_pct),
                 upload_util_pct = COALESCE(excluded.upload_util_pct, wan_link_current_status.upload_util_pct),
                 admin_status = excluded.admin_status, oper_status = excluded.oper_status,
                 collection_status = excluded.collection_status, health_status = excluded.health_status,
                 active_alert_count = excluded.active_alert_count,
                 last_success_at = COALESCE(excluded.last_success_at, wan_link_current_status.last_success_at),
                 consecutive_down_count = excluded.consecutive_down_count, updated_at = excluded.updated_at""",
            (link["id"], sampled_at, derived["download_bps"], derived["upload_bps"], derived["download_util_pct"], derived["upload_util_pct"],
             status, status, collection_status, health, active_alerts, sampled_at if collection_status == "success" else None,
             previous_down_count + 1 if status == "down" else 0, sampled_at),
        )
        conn.commit()
        return {"link_id": link["id"], "collection_status": collection_status, "health_status": health}
    except Exception as exc:
        conn.rollback()
        return {"link_id": link["id"], "collection_status": "failed", "error": str(exc)}
    finally:
        conn.close()


def list_wan_link_options(*, site_id: str = "", device_id: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        device_clauses, device_params = [], []
        if site_id:
            # Devices historically stored the site relation in either `site_id`
            # or the legacy `site` column. Resolve both forms by stable site ID;
            # never compare the ID to the display name.
            device_clauses.append("(d.site_id = ? OR d.site = ? OR s.id = ?)")
            device_params.extend([site_id, site_id, site_id])
        if device_id:
            device_clauses.append("d.id = ?")
            device_params.append(device_id)
        device_clauses.append(
            "(LOWER(COALESCE(d.role, '')) IN ({roles}) OR LOWER(COALESCE(d.device_category, '')) IN ({categories}))".format(
                roles=','.join('?' for _ in _WAN_DEVICE_ROLES),
                categories=','.join('?' for _ in _WAN_DEVICE_CATEGORIES),
            )
        )
        device_params.extend([*_WAN_DEVICE_ROLES, *_WAN_DEVICE_CATEGORIES])
        device_where = f"WHERE {' AND '.join(device_clauses)}" if device_clauses else ""
        devices = [dict(row) for row in conn.execute(
            f"""SELECT d.id, d.hostname, d.ip_address, d.platform,
                       d.role, d.device_category,
                       COALESCE(NULLIF(d.site_id, ''), s.id, NULLIF(d.site, '')) AS site_id,
                       COALESCE(s.site_name, NULLIF(d.site, '')) AS site_name
                  FROM devices d
             LEFT JOIN sites s
                    ON s.id = NULLIF(d.site_id, '')
                    OR s.id = NULLIF(d.site, '')
                    OR s.site_name = NULLIF(d.site, '')
                {device_where}
              ORDER BY d.hostname, d.ip_address""",
            tuple(device_params),
        ).fetchall()]
        interface_params: list[Any] = []
        if device_id:
            interface_where = """WHERE device_id IN (
                SELECT d.id
                  FROM devices d
                 WHERE d.id = ?
                   AND (LOWER(COALESCE(d.role, '')) IN ({roles}) OR LOWER(COALESCE(d.device_category, '')) IN ({categories}))
            )""".format(
                roles=','.join('?' for _ in _WAN_DEVICE_ROLES),
                categories=','.join('?' for _ in _WAN_DEVICE_CATEGORIES),
            )
            interface_params.extend([device_id, *_WAN_DEVICE_ROLES, *_WAN_DEVICE_CATEGORIES])
        elif site_id:
            interface_where = """WHERE device_id IN (
                SELECT d.id
                  FROM devices d
             LEFT JOIN sites s
                    ON s.id = NULLIF(d.site_id, '')
                    OR s.id = NULLIF(d.site, '')
                    OR s.site_name = NULLIF(d.site, '')
                 WHERE (d.site_id = ? OR d.site = ? OR s.id = ?)
                   AND (LOWER(COALESCE(d.role, '')) IN ({roles}) OR LOWER(COALESCE(d.device_category, '')) IN ({categories}))
            )""".format(
                roles=','.join('?' for _ in _WAN_DEVICE_ROLES),
                categories=','.join('?' for _ in _WAN_DEVICE_CATEGORIES),
            )
            interface_params.extend([site_id, site_id, site_id, *_WAN_DEVICE_ROLES, *_WAN_DEVICE_CATEGORIES])
        elif not device_id:
            interface_where = """WHERE device_id IN (
                SELECT d.id
                  FROM devices d
             LEFT JOIN sites s
                    ON s.id = NULLIF(d.site_id, '')
                    OR s.id = NULLIF(d.site, '')
                    OR s.site_name = NULLIF(d.site, '')
                 WHERE LOWER(COALESCE(d.role, '')) IN ({roles})
                    OR LOWER(COALESCE(d.device_category, '')) IN ({categories})
            )""".format(
                roles=','.join('?' for _ in _WAN_DEVICE_ROLES),
                categories=','.join('?' for _ in _WAN_DEVICE_CATEGORIES),
            )
            interface_params.extend([*_WAN_DEVICE_ROLES, *_WAN_DEVICE_CATEGORIES])
        else:
            interface_where = ""
        interface_rows = [dict(row) for row in conn.execute(f"SELECT id, device_id, interface_name, if_index, description, speed, oper_status FROM interfaces {interface_where} ORDER BY device_id, interface_name", tuple(interface_params)).fetchall()]
        interfaces = _deduplicate_interface_options(interface_rows)
        sites = [dict(row) for row in conn.execute("SELECT id, site_name, site_code, timezone FROM sites ORDER BY site_name").fetchall()]
        return {"devices": devices, "interfaces": interfaces, "sites": sites}
    finally:
        conn.close()


def list_wan_links(*, page: int = 1, page_size: int = 20, site_id: str = "", provider: str = "", health_status: str = "", keyword: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        clauses: list[str] = []
        params: list[Any] = []
        if site_id:
            clauses.append("l.site_id = ?")
            params.append(site_id)
        if provider:
            clauses.append("l.provider = ?")
            params.append(provider)
        if keyword:
            clauses.append("(LOWER(l.link_name) LIKE LOWER(?) OR LOWER(l.interface_name) LIKE LOWER(?) OR LOWER(l.site_name) LIKE LOWER(?))")
            token = f"%{keyword}%"
            params.extend([token, token, token])
        if health_status:
            clauses.append("COALESCE(c.health_status, 'unknown') = ?")
            params.append(health_status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(conn.execute(f"SELECT COUNT(*) FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id {where}", tuple(params)).fetchone()[0])
        summary_row = conn.execute(
            f"""SELECT COUNT(*) AS total_links,
                       SUM(CASE WHEN COALESCE(c.health_status, 'unknown') = 'healthy' THEN 1 ELSE 0 END) AS healthy_links,
                       COALESCE(SUM(c.active_alert_count), 0) AS active_alerts,
                       COALESCE(SUM(c.download_bps), 0) AS download_bps,
                       COALESCE(SUM(c.upload_bps), 0) AS upload_bps,
                       COALESCE(MAX(CASE
                           WHEN COALESCE(c.download_bps * 100.0 / NULLIF(l.contracted_download_bps, 0), 0)
                              > COALESCE(c.upload_bps * 100.0 / NULLIF(l.contracted_upload_bps, 0), 0)
                           THEN c.download_bps * 100.0 / NULLIF(l.contracted_download_bps, 0)
                           ELSE c.upload_bps * 100.0 / NULLIF(l.contracted_upload_bps, 0)
                       END), 0) AS max_util_pct
                  FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id {where}""",
            tuple(params),
        ).fetchone()
        rows = conn.execute(
            f"""SELECT l.*, c.sampled_at, c.download_bps, c.upload_bps, c.download_util_pct,
                      c.upload_util_pct, c.admin_status, c.oper_status, c.collection_status,
                      c.health_status, c.active_alert_count, c.last_success_at
                 FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                {where} ORDER BY l.site_name, l.link_name LIMIT ? OFFSET ?""",
            tuple(params + [page_size, (page - 1) * page_size]),
        ).fetchall()
        items = [_apply_contract_utilization(dict(row)) for row in rows]
        return {"items": items, "total": total, "summary": dict(summary_row or {}), "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()


def _history_resolution(history_minutes: int) -> int:
    if history_minutes <= 60:
        return 60
    if history_minutes <= 360:
        return 300
    if history_minutes <= 1440:
        return 900
    if history_minutes <= 10080:
        return 3600
    return 7200


def _aggregate_history(rows: list[dict[str, Any]], step_seconds: int) -> list[dict[str, Any]]:
    if step_seconds <= 60:
        return rows
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            parsed = datetime.fromisoformat(str(row.get("sampled_at")).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            bucket = int(parsed.timestamp()) // step_seconds * step_seconds
        except (TypeError, ValueError):
            continue
        buckets.setdefault(bucket, []).append(row)
    average_keys = ("download_bps", "upload_bps", "download_util_pct", "upload_util_pct")
    sum_keys = ("in_error_delta", "out_error_delta", "in_discard_delta", "out_discard_delta")
    result: list[dict[str, Any]] = []
    for bucket, points in sorted(buckets.items()):
        item = dict(points[-1])
        item["sampled_at"] = datetime.fromtimestamp(bucket, tz=timezone.utc).replace(microsecond=0).isoformat()
        for key in average_keys:
            values = [float(point[key]) for point in points if point.get(key) is not None]
            item[key] = round(sum(values) / len(values), 3) if values else None
        for key in sum_keys:
            values = [int(point[key]) for point in points if point.get(key) is not None]
            item[key] = sum(values) if values else None
        result.append(item)
    return result


def get_wan_link_history(link_id: str, history_hours: int = 1, *, history_minutes: int | None = None) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        link = conn.execute("SELECT * FROM wan_links WHERE id = ?", (link_id,)).fetchone()
        if not link:
            return None
        duration_minutes = max(5, min(int(history_minutes if history_minutes is not None else history_hours * 60), 43_200))
        cutoff_dt = _now() - timedelta(minutes=duration_minutes)
        cutoff = _iso(cutoff_dt)
        if duration_minutes <= 360:
            history_source = "wan_link_samples_5m"
        elif duration_minutes <= 10_080:
            history_source = "wan_link_samples_1h"
        else:
            history_source = "wan_link_samples_1h"
        if duration_minutes > 60 and (_USE_PG or history_source != "wan_link_samples_1m"):
            rows = conn.execute(
                f"""SELECT '' AS id, link_id, bucket_start AS sampled_at,
                    avg_download_bps AS download_bps, avg_upload_bps AS upload_bps,
                    avg_download_util_pct AS download_util_pct, avg_upload_util_pct AS upload_util_pct,
                    in_error_total AS in_error_delta, out_error_total AS out_error_delta,
                    in_discard_total AS in_discard_delta, out_discard_total AS out_discard_delta,
                    CASE WHEN coverage_pct >= 80 THEN 'success' ELSE 'partial' END AS collection_status,
                    quality_flags, NULL AS oper_status
                    FROM {history_source} WHERE link_id = ? AND bucket_start >= ? ORDER BY bucket_start ASC""",
                (link_id, cutoff),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    f"SELECT * FROM {_sample_table()} WHERE link_id = ? AND sampled_at >= ? ORDER BY sampled_at ASC",
                    (link_id, cutoff),
                ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {_sample_table()} WHERE link_id = ? AND sampled_at >= ? ORDER BY sampled_at ASC",
                (link_id, cutoff),
            ).fetchall()
        events = conn.execute("SELECT * FROM wan_alert_events WHERE link_id = ? ORDER BY started_at DESC LIMIT 50", (link_id,)).fetchall()
        link_dict = dict(link)
        history_rows = [_apply_contract_utilization(dict(row)) for row in rows]
        return {
            "link": link_dict, "history_hours": round(duration_minutes / 60, 4), "history_minutes": duration_minutes, "resolution": _history_resolution(duration_minutes),
            "start_time": cutoff_dt.isoformat(), "end_time": _iso(),
            "history": _aggregate_history(history_rows, _history_resolution(duration_minutes)),
            "events": [dict(row) for row in events],
        }
    finally:
        conn.close()


def get_wan_link(link_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT l.*, c.sampled_at, c.download_bps, c.upload_bps, c.download_util_pct,
                      c.upload_util_pct, c.admin_status, c.oper_status, c.collection_status,
                      c.health_status, c.active_alert_count, c.last_success_at
                 FROM wan_links l LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                WHERE l.id = ?""",
            (link_id,),
        ).fetchone()
        item = _row_dict(row)
        return _apply_contract_utilization(item) if item else None
    finally:
        conn.close()


def list_wan_alert_events(*, page: int = 1, page_size: int = 20, status: str = "", severity: str = "", link_id: str = "", keyword: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("e.status", status), ("e.severity", severity), ("e.link_id", link_id)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if keyword:
            clauses.append("(LOWER(e.title) LIKE LOWER(?) OR LOWER(e.message) LIKE LOWER(?) OR LOWER(l.link_name) LIKE LOWER(?))")
            token = f"%{keyword}%"
            params.extend([token, token, token])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(conn.execute(f"SELECT COUNT(*) FROM wan_alert_events e JOIN wan_links l ON l.id = e.link_id {where}", tuple(params)).fetchone()[0])
        rows = conn.execute(
            f"""SELECT e.*, l.link_name, l.site_name, l.provider
                 FROM wan_alert_events e JOIN wan_links l ON l.id = e.link_id
                {where} ORDER BY e.started_at DESC LIMIT ? OFFSET ?""",
            tuple(params + [page_size, (page - 1) * page_size]),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()


async def test_wan_link_collection(link_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        link = _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ?", (link_id,)).fetchone())
        if not link:
            return None
        device = _row_dict(conn.execute("SELECT * FROM devices WHERE id = ?", (link["device_id"],)).fetchone()) or {}
    finally:
        conn.close()
    credential = resolve_collector_credentials(device)
    snmp = credential.get("snmp") or {}
    ip = str(snmp.get("server") or device.get("ip_address") or "").strip()
    community = str(snmp.get("community") or "").strip()
    port = int(snmp.get("port") or device.get("snmp_port") or 161)
    if not ip or not community:
        return {"link_id": link_id, "status": "not_configured", "error_code": "not_configured", "items": []}
    interface_config = resolve_metric_profiles(device).get('interface') or None
    detail = await collect_interface_data_detailed(ip, community, port, interface_config)
    matched = _match_interface(link, detail.get("items") or [])
    if detail.get("status") == "success" and not matched:
        return {"link_id": link_id, "status": "interface_not_found", "error_code": "interface_not_found", "items": []}
    return {"link_id": link_id, "status": detail.get("status"), "error_code": detail.get("error_code"), "items": [matched] if matched else []}


def upsert_wan_link(payload: dict[str, Any], link_id: str | None = None) -> dict[str, Any]:
    conn = get_db_connection()
    now = _iso()
    try:
        device_id = str(payload.get("device_id") or "").strip()
        interface_id = str(payload.get("interface_id") or "").strip()
        if not device_id or not interface_id:
            raise ValueError("device_id and interface_id are required")
        device = _row_dict(conn.execute("SELECT id, hostname, site, site_id FROM devices WHERE id = ?", (device_id,)).fetchone())
        iface = _row_dict(conn.execute("SELECT * FROM interfaces WHERE id = ? AND device_id = ?", (interface_id, device_id)).fetchone())
        if not device or not iface:
            raise ValueError("Selected device or interface does not exist")
        site_id = str(payload.get("site_id") or "").strip()
        site = _row_dict(conn.execute("SELECT id, site_name, timezone FROM sites WHERE id = ?", (site_id,)).fetchone()) if site_id else None
        if site_id and not site:
            raise ValueError("Selected site does not exist")
        device_site_id = str(device.get("site_id") or "").strip()
        device_site_value = str(device.get("site") or "").strip()
        selected_site_values = {
            str(site.get("id") or "").strip(),
            str(site.get("site_name") or "").strip(),
        } if site else set()
        device_site_values = {value for value in (device_site_id, device_site_value) if value}
        if selected_site_values and device_site_values and not selected_site_values & device_site_values:
            raise ValueError("Selected device does not belong to the selected site")
        canonical_if_index = iface.get("if_index")
        if canonical_if_index is None:
            raise ValueError("if_index is required; run an SNMP interface sync first")
        if str(payload.get("link_role") or "primary") not in {"primary", "backup", "load_balanced"}:
            raise ValueError("link_role must be primary, backup or load_balanced")
        if str(payload.get("direction_mode") or "normal") not in {"normal", "reversed"}:
            raise ValueError("direction_mode must be normal or reversed")
        if link_id:
            existing = _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ?", (link_id,)).fetchone())
            if not existing:
                raise ValueError("WAN link not found")
        link_id = link_id or str(payload.get("id") or f"wan-link-{uuid.uuid4().hex}")
        site_name = str(payload.get("site_name") or (site.get("site_name") if site else "") or device.get("site") or "").strip()
        down_mbps = _num(payload.get("contracted_download_mbps"))
        up_mbps = _num(payload.get("contracted_upload_mbps"))
        if down_mbps is None or up_mbps is None or down_mbps <= 0 or up_mbps <= 0:
            raise ValueError("contracted download/upload bandwidth must be greater than zero")
        values = {
            "id": link_id, "link_name": str(payload.get("link_name") or "").strip(), "site_id": site_id,
            "site_name": site_name, "device_id": device_id, "interface_id": interface_id,
            "interface_name": str(payload.get("interface_name") or iface.get("interface_name") or ""),
            "if_index": int(canonical_if_index), "provider": str(payload.get("provider") or ""),
            "circuit_number": str(payload.get("circuit_number") or ""), "public_ip": str(payload.get("public_ip") or ""),
            "link_type": str(payload.get("link_type") or "Internet"), "link_role": str(payload.get("link_role") or "primary"),
            "direction_mode": str(payload.get("direction_mode") or "normal"), "contracted_download_bps": int(round(down_mbps * 1_000_000)),
            "contracted_upload_bps": int(round(up_mbps * 1_000_000)), "collection_interval_sec": int(payload.get("collection_interval_sec") or 60),
            "timezone": str(payload.get("timezone") or (site.get("timezone") if site else None) or "Asia/Shanghai"), "enabled": bool(payload.get("enabled", True)),
            "maintenance_window": str(payload.get("maintenance_window") or ""), "notes": str(payload.get("notes") or ""),
            "created_at": now, "updated_at": now,
        }
        if not values["link_name"]:
            raise ValueError("link_name is required")
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column not in {"id", "created_at"})
        conn.execute(f"INSERT INTO wan_links ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}", tuple(values[column] for column in columns))
        _ensure_alert_rules(conn, values, now)
        conn.execute(
            """UPDATE wan_link_current_status
                  SET download_util_pct = CASE
                          WHEN download_bps IS NULL THEN NULL
                          ELSE download_bps * 100.0 / NULLIF(?, 0)
                      END,
                      upload_util_pct = CASE
                          WHEN upload_bps IS NULL THEN NULL
                          ELSE upload_bps * 100.0 / NULLIF(?, 0)
                      END,
                      updated_at = ?
                WHERE link_id = ?""",
            (values["contracted_download_bps"], values["contracted_upload_bps"], now, link_id),
        )
        conn.commit()
        return _row_dict(conn.execute("SELECT * FROM wan_links WHERE id = ?", (link_id,)).fetchone()) or values
    finally:
        conn.close()


def delete_wan_link(link_id: str) -> bool:
    conn = get_db_connection()
    try:
        exists = conn.execute("SELECT 1 FROM wan_links WHERE id = ?", (link_id,)).fetchone()
        if not exists:
            return False
        conn.execute("DELETE FROM wan_alert_events WHERE link_id = ?", (link_id,))
        conn.execute("DELETE FROM wan_alert_rules WHERE link_id = ?", (link_id,))
        for table in ("wan_probe_bindings", "wan_link_group_members", "wan_maintenance_windows", "wan_correlation_events", "wan_capacity_recommendations"):
            column = "group_id" if table == "wan_link_group_members" else "id" if table == "wan_maintenance_windows" else "link_id"
            if table == "wan_maintenance_windows":
                conn.execute("DELETE FROM wan_maintenance_windows WHERE link_id = ?", (link_id,))
            elif table == "wan_link_group_members":
                conn.execute("DELETE FROM wan_link_group_members WHERE link_id = ?", (link_id,))
            else:
                conn.execute(f"DELETE FROM {table} WHERE link_id = ?", (link_id,))
        conn.execute("DELETE FROM wan_link_current_status WHERE link_id = ?", (link_id,))
        conn.execute(f"DELETE FROM {_sample_table()} WHERE link_id = ?", (link_id,))
        if _USE_PG:
            conn.execute("DELETE FROM wan_link_samples_1m WHERE link_id = ?", (link_id,))
        conn.execute("DELETE FROM wan_links WHERE id = ?", (link_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def run_wan_collection_once() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        links = [dict(row) for row in conn.execute("SELECT * FROM wan_links WHERE enabled = TRUE ORDER BY id").fetchall()]
    finally:
        conn.close()
    if not links:
        return {"success": True, "total": 0, "results": []}
    async def _run() -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
        for link in links:
            grouped.setdefault((str(link.get("device_id")), str(link.get("snmp_server") or ""), int(link.get("snmp_port") or 161)), []).append(link)

        async def collect_group(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
            first = group[0]
            conn = get_db_connection()
            try:
                device_row = conn.execute("SELECT * FROM devices WHERE id = ?", (first["device_id"],)).fetchone()
                device = _row_dict(device_row) or {}
            finally:
                conn.close()
            credential = resolve_collector_credentials(device)
            snmp = credential.get("snmp") or {}
            ip = str(snmp.get("server") or device.get("ip_address") or "").strip()
            community = str(snmp.get("community") or "").strip()
            port = int(snmp.get("port") or device.get("snmp_port") or 161)
            interface_config = resolve_metric_profiles(device).get('interface') or None
            detail = {"status": "not_configured", "items": [], "error_code": "not_configured", "error_message": "SNMP credentials are not configured"}
            if ip and community:
                detail = await collect_interface_data_detailed(ip, community, port, interface_config)
            return await asyncio.gather(*[_collect_link(link, detail) for link in group])

        grouped_results = await asyncio.gather(*[collect_group(group) for group in grouped.values()])
        return [item for group in grouped_results for item in group]
    results = asyncio.run(_run())
    return {"success": True, "total": len(results), "results": results}
