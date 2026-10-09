"""Internal aggregate and per-device hardware Prometheus metrics for Grafana.

The aggregate endpoint avoids device-level series. Hardware inventory is
exported from a separate route keyed by stable asset/device IDs. Neither route
exports device addresses, raw sysDescr, alert text, recipient data, credentials,
or raw errors; both are intended for the internal monitoring network only.
"""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Response

from database import _USE_PG, get_db_connection


logger = logging.getLogger(__name__)
router = APIRouter(tags=["internal metrics"])

_ALERT_SEVERITIES = (
    "critical",
    "major",
    "warning",
    "minor",
    "high",
    "medium",
    "low",
    "info",
    "unknown",
)
_DELIVERY_CHANNELS = (
    "workspace",
    "feishu",
    "dingtalk",
    "wechat",
    "email",
    "global_webhook",
    "unknown",
)
_DELIVERY_STATUSES = ("queued", "sending", "retrying", "succeeded", "failed", "skipped", "unknown")
_OUTBOX_STATUSES = ("pending", "processing", "succeeded", "failed", "unknown")
_PROBE_TYPES = ("TCP_CONNECT", "HTTP_GET", "HTTPS_GET", "DNS_RESOLVE", "ICMP_PING", "unknown")
_WAN_HEALTH_STATES = ("healthy", "degraded", "warning", "critical", "unavailable", "unknown")


def _label(value: str) -> str:
    """Escape a Prometheus label value even though all values are allowlisted."""

    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, value: Any, labels: dict[str, str] | None = None) -> str:
    if isinstance(value, bool):
        number = "1" if value else "0"
    elif isinstance(value, int):
        number = str(value)
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return ""
        if not math.isfinite(numeric):
            return ""
        number = f"{numeric:.6f}".rstrip("0").rstrip(".")
        if number in {"", "-0"}:
            number = "0"
    if labels:
        rendered = ",".join(f'{key}="{_label(value)}"' for key, value in labels.items())
        return f"{name}{{{rendered}}} {number}"
    return f"{name} {number}"


def _append_header(lines: list[str], name: str, help_text: str) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")


def _safe_query(
    conn: Any,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[Any] | None:
    """Run one optional source query without exposing DB failures to scrapers."""

    try:
        return conn.execute(sql, params).fetchall()
    except Exception as exc:  # source tables may not exist on older installs
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug("Grafana metrics source unavailable (%s)", type(exc).__name__)
        return None


def _safe_scalar(
    conn: Any,
    sql: str,
    params: tuple[Any, ...] = (),
) -> Any | None:
    rows = _safe_query(conn, sql, params)
    if rows is None or not rows:
        return None
    row = rows[0]
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    try:
        return row[0]
    except (IndexError, TypeError):
        return None


def _row_value(row: Any, key: str, index: int = 0, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[index]
    except (IndexError, TypeError):
        return default


def _numeric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_values(rows: list[Any], now: datetime, start_key: str, end_key: str | None = None) -> list[float]:
    values: list[float] = []
    for row in rows:
        start = _parse_utc(_row_value(row, start_key, 0))
        end = _parse_utc(_row_value(row, end_key, 1)) if end_key else now
        if start is None or end is None:
            continue
        seconds = (end - start).total_seconds()
        if math.isfinite(seconds) and seconds >= 0:
            values.append(seconds)
    return values


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _severity_case(column: str = "severity") -> str:
    values = ", ".join(f"'{severity}'" for severity in _ALERT_SEVERITIES[:-1])
    return f"CASE WHEN LOWER(COALESCE({column}, '')) IN ({values}) THEN LOWER({column}) ELSE 'unknown' END"


def _allowlist_case(column: str, values: tuple[str, ...]) -> str:
    known = values[:-1]
    quoted = ", ".join(f"'{value}'" for value in known)
    return f"CASE WHEN LOWER(COALESCE({column}, '')) IN ({quoted}) THEN LOWER({column}) ELSE 'unknown' END"


def _collect_outbound(lines: list[str], conn: Any, cutoffs: dict[str, str]) -> None:
    names = {
        "samples": "nexora_outbound_probe_samples",
        "availability": "nexora_outbound_probe_availability_ratio",
        "avg": "nexora_outbound_probe_latency_avg_ms",
        "max": "nexora_outbound_probe_latency_max_ms",
    }
    family_lines: list[str] = []
    _append_header(family_lines, names["samples"], "Aggregate outbound probe result samples in the rolling window.")
    _append_header(
        family_lines,
        names["availability"],
        "Aggregate outbound probe success ratio in the rolling window; this is not per-circuit WAN SLA.",
    )
    _append_header(
        family_lines,
        names["avg"],
        "Success-weighted average of per-run outbound probe execution timing in milliseconds.",
    )
    _append_header(
        family_lines,
        names["max"],
        "Maximum per-run average outbound probe execution timing in milliseconds.",
    )

    sql = """
        SELECT SUM(total_targets) AS sample_count,
               SUM(success_count) AS success_count,
               SUM(CASE WHEN success_count > 0 AND avg_latency_ms IS NOT NULL
                        THEN avg_latency_ms * success_count ELSE 0 END)
                   / NULLIF(SUM(CASE WHEN success_count > 0 AND avg_latency_ms IS NOT NULL
                                     THEN success_count ELSE 0 END), 0)
                   AS avg_latency_ms,
               MAX(CASE WHEN success_count > 0 THEN avg_latency_ms END) AS max_latency_ms
          FROM outbound_probe_samples
         WHERE timestamp >= ?
    """
    for window in ("1h", "24h"):
        rows = _safe_query(conn, sql, (cutoffs[window],))
        if rows is None:
            # The source family may be unavailable on an older deployment.
            return
        row = rows[0] if rows else None
        sample_count = int(_numeric(_row_value(row, "sample_count", 0, 0), 0)) if row else 0
        success_count = int(_numeric(_row_value(row, "success_count", 1, 0), 0)) if row else 0
        family_lines.append(_metric_line(names["samples"], sample_count, {"window": window}))
        if sample_count > 0:
            family_lines.append(
                _metric_line(
                    names["availability"],
                    success_count / sample_count,
                    {"window": window},
                )
            )
        avg_latency = _row_value(row, "avg_latency_ms", 2) if row else None
        max_latency = _row_value(row, "max_latency_ms", 3) if row else None
        if avg_latency is not None:
            family_lines.append(_metric_line(names["avg"], _numeric(avg_latency), {"window": window}))
        if max_latency is not None:
            family_lines.append(_metric_line(names["max"], _numeric(max_latency), {"window": window}))
    lines.extend(family_lines)


def _collect_outbound_protocols(lines: list[str], conn: Any, cutoffs: dict[str, str]) -> None:
    metric_names = {
        "samples": "nexora_outbound_probe_samples_by_type",
        "success": "nexora_outbound_probe_success_ratio_by_type",
        "timeouts": "nexora_outbound_probe_timeouts_by_type",
        "timeout_ratio": "nexora_outbound_probe_timeout_ratio_by_type",
        "latency_avg": "nexora_outbound_probe_latency_avg_ms_by_type",
        "latency_max": "nexora_outbound_probe_latency_max_ms_by_type",
        "icmp_loss": "nexora_outbound_probe_icmp_packet_loss_ratio",
        "icmp_jitter": "nexora_outbound_probe_icmp_jitter_avg_ms",
    }
    family_lines: list[str] = []
    help_texts = {
        "samples": "Outbound probe result samples in the rolling window by fixed protocol type.",
        "success": "Successful outbound probe ratio in the rolling window by fixed protocol type.",
        "timeouts": "Outbound probe timeout samples in the rolling window by fixed protocol type.",
        "timeout_ratio": "Outbound probe timeout ratio in the rolling window by fixed protocol type.",
        "latency_avg": "Average successful probe response latency in milliseconds by fixed protocol type.",
        "latency_max": "Maximum successful probe response latency in milliseconds by fixed protocol type.",
        "icmp_loss": "Average packet loss ratio measured across each multi-echo ICMP sample.",
        "icmp_jitter": "Average per-sample mean absolute delay variation between consecutive ICMP echo replies.",
    }
    for key, name in metric_names.items():
        _append_header(family_lines, name, help_texts[key])

    sql = """
        SELECT UPPER(COALESCE(probe_type, 'UNKNOWN')) AS probe_type,
               COUNT(*) AS sample_count,
               SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) AS success_count,
               SUM(CASE WHEN UPPER(COALESCE(error_type, '')) = 'CONNECT_TIMEOUT' THEN 1 ELSE 0 END) AS timeout_count,
               AVG(CASE WHEN success = TRUE THEN latency_ms END) AS latency_avg_ms,
               MAX(CASE WHEN success = TRUE THEN latency_ms END) AS latency_max_ms,
               AVG(packet_loss_percent) AS packet_loss_percent_avg,
               AVG(rtt_jitter_ms) AS rtt_jitter_avg_ms
          FROM outbound_probe_results
         WHERE sampled_at >= ?
         GROUP BY 1
    """
    collected: list[tuple[str, dict[str, dict[str, float]]]] = []
    for window in ("1h", "24h"):
        rows = _safe_query(conn, sql, (cutoffs[window],))
        if rows is None:
            return
        counts = {
            probe_type: {
                "samples": 0,
                "success_count": 0,
                "timeouts": 0,
            }
            for probe_type in _PROBE_TYPES
        }
        for row in rows:
            probe_type = str(_row_value(row, "probe_type", 0, "unknown") or "unknown").upper()
            if probe_type not in _PROBE_TYPES[:-1]:
                probe_type = "unknown"
            item = counts[probe_type]
            for key, column, index in (
                ("samples", "sample_count", 1),
                ("success_count", "success_count", 2),
                ("timeouts", "timeout_count", 3),
            ):
                item[key] = int(_numeric(_row_value(row, column, index, 0), 0))
            for key, column, index in (
                ("latency_avg", "latency_avg_ms", 4),
                ("latency_max", "latency_max_ms", 5),
                ("icmp_loss_percent", "packet_loss_percent_avg", 6),
                ("icmp_jitter", "rtt_jitter_avg_ms", 7),
            ):
                value = _row_value(row, column, index)
                if value is not None:
                    item[key] = _numeric(value)
        collected.append((window, counts))

    for window, counts in collected:
        for probe_type, item in counts.items():
            labels = {"window": window, "probe_type": probe_type.lower()}
            samples = int(item["samples"])
            family_lines.append(_metric_line(metric_names["samples"], samples, labels))
            if samples > 0:
                family_lines.append(_metric_line(metric_names["timeouts"], int(item["timeouts"]), labels))
                family_lines.append(_metric_line(metric_names["timeout_ratio"], item["timeouts"] / samples, labels))
                family_lines.append(_metric_line(metric_names["success"], item["success_count"] / samples, labels))
            if "latency_avg" in item:
                family_lines.append(_metric_line(metric_names["latency_avg"], item["latency_avg"], labels))
            if "latency_max" in item:
                family_lines.append(_metric_line(metric_names["latency_max"], item["latency_max"], labels))
            if probe_type == "ICMP_PING" and "icmp_loss_percent" in item:
                family_lines.append(
                    _metric_line(metric_names["icmp_loss"], item["icmp_loss_percent"] / 100, {"window": window})
                )
            if probe_type == "ICMP_PING" and "icmp_jitter" in item:
                family_lines.append(_metric_line(metric_names["icmp_jitter"], item["icmp_jitter"], {"window": window}))
    lines.extend(family_lines)


def _collect_wan(lines: list[str], conn: Any, cutoffs: dict[str, str]) -> None:
    sample_table = "wan_link_samples_1m_partitioned" if _USE_PG else "wan_link_samples_1m"
    status_name = "nexora_wan_links_by_health_status"
    status_rows = _safe_query(
        conn,
        f"""
            SELECT LOWER(COALESCE(s.health_status, 'unknown')) AS status, COUNT(*) AS link_count
              FROM wan_link_current_status s
              JOIN wan_links l ON l.id = s.link_id
             WHERE l.enabled = TRUE
             GROUP BY 1
        """,
    )
    if status_rows is not None:
        _append_header(lines, status_name, "Aggregate enabled WAN link interface health state counts.")
        counts = {state: 0 for state in _WAN_HEALTH_STATES}
        for row in status_rows:
            status = str(_row_value(row, "status", 0, "unknown") or "unknown").lower()
            if status not in counts:
                status = "unknown"
            counts[status] += int(_numeric(_row_value(row, "link_count", 1, 0), 0))
        for status, value in counts.items():
            lines.append(_metric_line(status_name, value, {"status": status}))

    outage_rows = _safe_query(
        conn,
        """
            SELECT c.oper_status, c.admin_status, c.collection_status,
                   c.consecutive_down_count, c.sampled_at, l.collection_interval_sec
              FROM wan_link_current_status c
              JOIN wan_links l ON l.id = c.link_id
             WHERE l.enabled = TRUE
        """,
    )
    if outage_rows is not None:
        active_down = 0
        outage_seconds: list[float] = []
        for row in outage_rows:
            if str(_row_value(row, "collection_status", 2, "") or "").lower() != "success":
                continue
            if str(_row_value(row, "admin_status", 1, "") or "").lower() not in {"up", "1"}:
                continue
            if str(_row_value(row, "oper_status", 0, "") or "").lower() not in {"down", "2"}:
                continue
            sampled_at = _parse_utc(_row_value(row, "sampled_at", 4))
            if sampled_at is None:
                continue
            interval = max(1, int(_numeric(_row_value(row, "collection_interval_sec", 5, 60), 60)))
            sample_age = max(0.0, (datetime.now(timezone.utc) - sampled_at).total_seconds())
            if sample_age > max(interval * 2, 180):
                continue
            down_count = max(1, int(_numeric(_row_value(row, "consecutive_down_count", 3, 0), 0)))
            active_down += 1
            outage_seconds.append(float(down_count * interval))
        active_name = "nexora_wan_interface_active_down_links"
        duration_name = "nexora_wan_interface_continuous_down_estimate_max_seconds"
        _append_header(lines, active_name, "Enabled WAN interfaces with a fresh successful sample reporting admin-up and oper-down.")
        _append_header(lines, duration_name, "Maximum estimated continuous WAN interface outage based on consecutive down samples and collection interval.")
        lines.append(_metric_line(active_name, active_down))
        lines.append(_metric_line(duration_name, max(outage_seconds, default=0)))

    metric_names = {
        "samples": "nexora_wan_interface_samples",
        "collection_success": "nexora_wan_interface_collection_success_ratio",
        "oper_up": "nexora_wan_interface_oper_up_ratio",
        "download": "nexora_wan_interface_avg_download_bps",
        "upload": "nexora_wan_interface_avg_upload_bps",
        "errors": "nexora_wan_interface_errors_total",
        "discards": "nexora_wan_interface_discards_total",
    }
    family_lines: list[str] = []
    for key, name in metric_names.items():
        _append_header(family_lines, name, f"Aggregate enabled WAN interface {key} over the rolling window.")

    sql = f"""
        SELECT COUNT(*) AS sample_count,
               SUM(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success' THEN 1 ELSE 0 END) AS collected_count,
               SUM(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success'
                          AND LOWER(COALESCE(s.admin_status, '')) IN ('up', '1') THEN 1 ELSE 0 END) AS admin_up_count,
               SUM(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success'
                          AND LOWER(COALESCE(s.admin_status, '')) IN ('up', '1')
                          AND LOWER(COALESCE(s.oper_status, '')) IN ('up', '1') THEN 1 ELSE 0 END) AS oper_up_count,
               AVG(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success' THEN s.download_bps END) AS avg_download_bps,
               AVG(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success' THEN s.upload_bps END) AS avg_upload_bps,
               SUM(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success'
                        THEN COALESCE(s.in_error_delta, 0) + COALESCE(s.out_error_delta, 0) ELSE 0 END) AS errors_total,
               SUM(CASE WHEN LOWER(COALESCE(s.collection_status, '')) = 'success'
                        THEN COALESCE(s.in_discard_delta, 0) + COALESCE(s.out_discard_delta, 0) ELSE 0 END) AS discards_total
          FROM {sample_table} s
         WHERE s.sampled_at >= ?
           AND EXISTS (SELECT 1 FROM wan_links l WHERE l.id = s.link_id AND l.enabled = TRUE)
    """
    for window in ("1h", "24h"):
        rows = _safe_query(conn, sql, (cutoffs[window],))
        if rows is None:
            return
        row = rows[0] if rows else None
        if not row:
            continue
        labels = {"window": window}
        sample_count = int(_numeric(_row_value(row, "sample_count", 0, 0), 0))
        collected_count = int(_numeric(_row_value(row, "collected_count", 1, 0), 0))
        admin_up_count = int(_numeric(_row_value(row, "admin_up_count", 2, 0), 0))
        oper_up_count = int(_numeric(_row_value(row, "oper_up_count", 3, 0), 0))
        family_lines.append(_metric_line(metric_names["samples"], sample_count, labels))
        if sample_count:
            family_lines.append(_metric_line(metric_names["collection_success"], collected_count / sample_count, labels))
        if admin_up_count:
            family_lines.append(_metric_line(metric_names["oper_up"], oper_up_count / admin_up_count, labels))
        for key, column, index in (
            ("download", "avg_download_bps", 4),
            ("upload", "avg_upload_bps", 5),
            ("errors", "errors_total", 6),
            ("discards", "discards_total", 7),
        ):
            value = _row_value(row, column, index)
            if value is not None:
                family_lines.append(_metric_line(metric_names[key], _numeric(value), labels))
    lines.extend(family_lines)


def _collect_alerts(
    lines: list[str],
    conn: Any,
    cutoff_24h: str,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    open_name = "nexora_alert_open_events"
    _append_header(lines, open_name, "Currently open aggregate alert events by normalized severity.")
    severity_sql = _severity_case("severity")
    open_rows = _safe_query(
        conn,
        f"""
            SELECT {severity_sql} AS severity, COUNT(*) AS event_count
              FROM alert_events
             WHERE resolved_at IS NULL
               AND COALESCE(workflow_status, 'open') <> 'suppressed'
             GROUP BY 1
        """,
    )
    if open_rows is None:
        del lines[-2:]
    else:
        counts = {severity: 0 for severity in _ALERT_SEVERITIES}
        for row in open_rows:
            severity = str(_row_value(row, "severity", 0, "unknown") or "unknown").lower()
            if severity not in counts:
                severity = "unknown"
            counts[severity] += int(_numeric(_row_value(row, "event_count", 1, 0), 0))
        for severity in _ALERT_SEVERITIES:
            lines.append(_metric_line(open_name, counts[severity], {"severity": severity}))

    count_specs = (
        ("nexora_alert_events_created_24h", "created_at"),
        ("nexora_alert_events_acknowledged_24h", "ack_at"),
        ("nexora_alert_events_resolved_24h", "resolved_at"),
    )
    for name, column in count_specs:
        _append_header(lines, name, f"Aggregate alert events with {column} in the last 24 hours.")
        value = _safe_scalar(
            conn,
            f"SELECT COUNT(*) FROM alert_events WHERE {column} IS NOT NULL AND {column} >= ?",
            (cutoff_24h,),
        )
        if value is not None:
            lines.append(_metric_line(name, int(_numeric(value)), None))
        else:
            del lines[-2:]

    open_duration_rows = _safe_query(
        conn,
        """
            SELECT created_at
              FROM alert_events
             WHERE resolved_at IS NULL
               AND COALESCE(workflow_status, 'open') <> 'suppressed'
        """,
    )
    if open_duration_rows is not None:
        durations = _duration_values(open_duration_rows, now, "created_at")
        oldest_name = "nexora_alert_open_duration_oldest_seconds"
        p95_name = "nexora_alert_open_duration_p95_seconds"
        _append_header(lines, oldest_name, "Age in seconds of the oldest currently open, non-suppressed alert.")
        _append_header(lines, p95_name, "95th percentile age in seconds of currently open, non-suppressed alerts.")
        lines.append(_metric_line(oldest_name, max(durations, default=0)))
        lines.append(_metric_line(p95_name, _percentile(durations, 0.95) or 0))

    lifecycle_specs = (
        (
            "mtta",
            "ack_at",
            "nexora_alert_mtta_seconds_24h",
            "nexora_alert_mtta_samples_24h",
            "nexora_alert_mtta_p95_seconds_24h",
        ),
        (
            "mttr",
            "resolved_at",
            "nexora_alert_mttr_seconds_24h",
            "nexora_alert_mttr_samples_24h",
            "nexora_alert_mttr_p95_seconds_24h",
        ),
    )
    for _metric_key, event_column, duration_name, samples_name, p95_name in lifecycle_specs:
        rows = _safe_query(
            conn,
            f"""
                SELECT created_at, {event_column}
                  FROM alert_events
                 WHERE {event_column} IS NOT NULL
                   AND {event_column} >= ?
                   AND created_at IS NOT NULL
            """,
            (cutoff_24h,),
        )
        if rows is None:
            continue
        durations = _duration_values(rows, now, "created_at", event_column)
        _append_header(lines, samples_name, f"Number of alert events used to calculate {duration_name}.")
        lines.append(_metric_line(samples_name, len(durations)))
        if durations:
            _append_header(lines, duration_name, f"Mean seconds from alert creation to {event_column} in the last 24 hours.")
            lines.append(_metric_line(duration_name, sum(durations) / len(durations)))
            _append_header(lines, p95_name, f"95th percentile seconds from alert creation to {event_column} in the last 24 hours.")
            lines.append(_metric_line(p95_name, _percentile(durations, 0.95) or 0))

    duplicate_name = "nexora_alert_duplicate_open_events"
    _append_header(lines, duplicate_name, "Extra unresolved alert rows beyond one per dedupe key, excluding suppressed alerts.")
    duplicate_count = _safe_scalar(
        conn,
        """
            SELECT COALESCE(SUM(duplicate_count - 1), 0)
              FROM (
                    SELECT COUNT(*) AS duplicate_count
                      FROM alert_events
                     WHERE resolved_at IS NULL
                       AND COALESCE(workflow_status, 'open') <> 'suppressed'
                     GROUP BY dedupe_key
                    HAVING COUNT(*) > 1
              ) duplicate_groups
        """,
    )
    if duplicate_count is None:
        del lines[-2:]
    else:
        lines.append(_metric_line(duplicate_name, int(_numeric(duplicate_count, 0))))


def _collect_delivery(lines: list[str], conn: Any, cutoff_24h: str) -> None:
    attempts_name = "nexora_alert_delivery_attempts_24h"
    outbox_name = "nexora_alert_outbox_items"
    _append_header(lines, attempts_name, "Aggregate alert delivery attempts created in the last 24 hours.")
    attempts_rows = _safe_query(
        conn,
        f"""
            SELECT {_allowlist_case('channel', _DELIVERY_CHANNELS)} AS channel,
                   {_allowlist_case('status', _DELIVERY_STATUSES)} AS status,
                   COUNT(*) AS item_count
              FROM alert_delivery_attempts
             WHERE created_at >= ?
             GROUP BY 1, 2
        """,
        (cutoff_24h,),
    )
    if attempts_rows is None:
        del lines[-2:]
    else:
        counts = {
            (channel, status): 0
            for channel in _DELIVERY_CHANNELS
            for status in _DELIVERY_STATUSES
        }
        for row in attempts_rows:
            channel = str(_row_value(row, "channel", 0, "unknown") or "unknown").lower()
            status = str(_row_value(row, "status", 1, "unknown") or "unknown").lower()
            if channel not in _DELIVERY_CHANNELS:
                channel = "unknown"
            if status not in _DELIVERY_STATUSES:
                status = "unknown"
            counts[(channel, status)] += int(_numeric(_row_value(row, "item_count", 2, 0)))
        for channel in _DELIVERY_CHANNELS:
            for status in _DELIVERY_STATUSES:
                lines.append(
                    _metric_line(
                        attempts_name,
                        counts[(channel, status)],
                        {"channel": channel, "status": status},
                    )
                )

    retried_name = "nexora_alert_retried_deliveries_24h"
    _append_header(lines, retried_name, "Alert delivery IDs with more than one recorded attempt in the last 24 hours.")
    retried_count = _safe_scalar(
        conn,
        """
            SELECT COUNT(*)
              FROM (
                    SELECT delivery_id
                      FROM alert_delivery_attempts
                     WHERE created_at >= ?
                     GROUP BY delivery_id
                    HAVING COUNT(*) > 1
              ) retried_deliveries
        """,
        (cutoff_24h,),
    )
    if retried_count is None:
        del lines[-2:]
    else:
        lines.append(_metric_line(retried_name, int(_numeric(retried_count, 0))))

    _append_header(lines, outbox_name, "Aggregate alert delivery outbox items by normalized status.")
    outbox_rows = _safe_query(
        conn,
        f"""
            SELECT {_allowlist_case('status', _OUTBOX_STATUSES)} AS status,
                   COUNT(*) AS item_count
              FROM alert_delivery_outbox
             GROUP BY 1
        """,
    )
    if outbox_rows is None:
        del lines[-2:]
    else:
        counts = {status: 0 for status in _OUTBOX_STATUSES}
        for row in outbox_rows:
            status = str(_row_value(row, "status", 0, "unknown") or "unknown").lower()
            if status not in _OUTBOX_STATUSES:
                status = "unknown"
            counts[status] += int(_numeric(_row_value(row, "item_count", 1, 0)))
        for status in _OUTBOX_STATUSES:
            lines.append(
                _metric_line(
                    outbox_name,
                    counts[status],
                    {"status": status},
                )
            )


def _hardware_stale_after_seconds(sensor: dict[str, Any]) -> float:
    from services.snmp_hardware_poller_service import hardware_stale_after_seconds

    return hardware_stale_after_seconds(sensor)


def _collect_hardware(lines: list[str], conn: Any, now: datetime) -> dict[str, Any]:
    """Expose current normalized hardware samples and per-category capability."""
    from services.snmp_hardware_inventory_service import (
        list_hardware_metric_rows,
        render_hardware_metrics,
    )
    from services.librenms_source_policy import (
        hardware_sensor_trust_cache_key,
        is_trusted_hardware_sensor,
    )
    from services.snmp_hardware_poller_service import DISCOVERY_VERSION

    timings: dict[str, float] = {}
    rows = list_hardware_metric_rows(conn, timings=timings, collection_version=DISCOVERY_VERSION)

    preparation_started = time.perf_counter()
    by_device: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    trust_cache: dict[tuple[Any, ...], bool] = {}
    trust_cache_hits = 0
    trust_cache_misses = 0
    trust_validation_seconds = 0.0
    for row in rows:
        trust_started = time.perf_counter()
        trust_key = hardware_sensor_trust_cache_key(row)
        trusted = trust_cache.get(trust_key)
        if trusted is None:
            trusted = is_trusted_hardware_sensor(row)
            trust_cache[trust_key] = trusted
            trust_cache_misses += 1
        else:
            trust_cache_hits += 1
        trust_validation_seconds += time.perf_counter() - trust_started
        if not trusted:
            continue
        device_id = str(row.get("device_id") or "")
        if not device_id:
            continue
        labels = {
            "tenant_id": row.get("tenant_id"),
            "asset_id": row.get("asset_id") or device_id,
            "device_id": device_id,
            "hostname": row.get("hostname"),
            "site_name": row.get("site_name"),
            "vendor": row.get("vendor"),
            "platform": row.get("platform"),
            "role": row.get("role"),
        }
        if device_id not in by_device:
            by_device[device_id] = (labels, [])
        sensor = dict(row)
        last_success = _parse_utc(sensor.get("last_success"))
        if str(sensor.get("last_quality") or "").casefold() == "good" and last_success is not None:
            if (now - last_success).total_seconds() > _hardware_stale_after_seconds(sensor):
                sensor["last_quality"] = "stale"
        by_device[device_id][1].append(sensor)
    timings["source_validation_ms"] = trust_validation_seconds * 1000
    timings["group_and_stale_ms"] = (time.perf_counter() - preparation_started) * 1000

    render_started = time.perf_counter()
    seen_headers: set[tuple[str, str]] = set()
    render_errors = 0
    for device_id in sorted(by_device):
        labels, sensors = by_device[device_id]
        try:
            rendered = render_hardware_metrics(sensors, labels)
        except Exception as exc:
            logger.warning("Grafana hardware renderer failed for device %s (%s)", device_id, type(exc).__name__)
            render_errors += 1
            continue
        for line in rendered.splitlines():
            if line.startswith("# HELP ") or line.startswith("# TYPE "):
                parts = line.split(" ", 3)
                key = (parts[1], parts[2]) if len(parts) >= 3 else (line, "")
                if key in seen_headers:
                    continue
                seen_headers.add(key)
            lines.append(line)
    timings["device_render_ms"] = (time.perf_counter() - render_started) * 1000

    capability_query_started = time.perf_counter()
    capability_rows = _safe_query(
        conn,
        """
        SELECT c.tenant_id, c.asset_id, c.device_id, d.hostname,
               COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''), '') AS site_name,
               d.vendor, d.platform, d.role, c.source_type, c.component_class,
               c.last_status, c.coverage_complete, c.active_sensor_count,
               c.last_discovered_count, c.reason, c.reason_code, c.rule_version,
               c.discovery_version, c.artifact_version, c.last_success_at
          FROM snmp_hardware_capabilities c
          JOIN devices d ON d.id = c.device_id
          LEFT JOIN physical_assets pa ON pa.id = d.asset_id
         LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
         WHERE c.discovery_version = ?
           AND c.source_type IN ('librenms_rule', 'librenms_os_rule', 'librenms_mib_rule')
         ORDER BY c.device_id, c.component_class, c.source_type
        """,
        (DISCOVERY_VERSION,),
    )
    timings["capability_query_ms"] = (time.perf_counter() - capability_query_started) * 1000
    if capability_rows is None:
        raise RuntimeError("hardware capability inventory query failed")
    capability_render_started = time.perf_counter()
    capability_name = "nexora_hw_capability_status"
    _append_header(lines, capability_name, "Last discovery status for one hardware source and component category.")
    active_count_name = "nexora_hw_capability_active_sensor_count"
    _append_header(lines, active_count_name, "Number of currently active discovered sensors in one hardware category.")
    discovered_count_name = "nexora_hw_capability_last_discovered_count"
    _append_header(lines, discovered_count_name, "Number of sensors in the latest accepted hardware discovery for one category.")
    capability_info_name = "nexora_hw_capability_info"
    _append_header(lines, capability_info_name, "Hardware capability versions and the last discovery reason code.")
    capability_success_name = "nexora_hw_capability_last_success_timestamp_seconds"
    _append_header(lines, capability_success_name, "Unix timestamp of the last complete successful hardware category discovery.")
    allowed_statuses = {"success", "partial", "failed", "unsupported", "not_found"}
    for row in capability_rows:
        status = str(_row_value(row, "last_status", 10, "unknown") or "unknown").casefold()
        if status not in allowed_statuses:
            status = "unknown"
        labels = {
            "tenant_id": _row_value(row, "tenant_id", 0),
            "asset_id": _row_value(row, "asset_id", 1) or _row_value(row, "device_id", 2),
            "device_id": _row_value(row, "device_id", 2),
            "hostname": _row_value(row, "hostname", 3),
            "site_name": _row_value(row, "site_name", 4),
            "vendor": _row_value(row, "vendor", 5),
            "platform": _row_value(row, "platform", 6),
            "role": _row_value(row, "role", 7),
            "source_type": _row_value(row, "source_type", 8),
            "component_class": _row_value(row, "component_class", 9),
            "status": status,
            "coverage_complete": str(bool(_row_value(row, "coverage_complete", 11))).lower(),
            "reason": str(_row_value(row, "reason", 14, "") or "")[:300],
            "reason_code": str(_row_value(row, "reason_code", 15, "") or ""),
            "rule_version": str(_row_value(row, "rule_version", 16, "") or ""),
            "discovery_version": str(_row_value(row, "discovery_version", 17, "") or ""),
            "artifact_version": str(_row_value(row, "artifact_version", 18, "") or ""),
        }
        lines.append(_metric_line(capability_name, 1, labels))
        active_count = max(0, int(_numeric(_row_value(row, "active_sensor_count", 12, 0))))
        discovered_count = max(0, int(_numeric(_row_value(row, "last_discovered_count", 13, 0))))
        lines.append(_metric_line(active_count_name, active_count, labels))
        lines.append(_metric_line(discovered_count_name, discovered_count, labels))
        lines.append(_metric_line(capability_info_name, 1, labels))
        successful_at = _parse_utc(_row_value(row, "last_success_at", 19))
        if successful_at is not None:
            lines.append(_metric_line(capability_success_name, successful_at.timestamp(), labels))

    render_error_name = "nexora_hw_sensor_render_errors"
    _append_header(lines, render_error_name, "Number of devices whose hardware metrics could not be rendered during this scrape.")
    lines.append(_metric_line(render_error_name, render_errors))
    timings["capability_render_ms"] = (time.perf_counter() - capability_render_started) * 1000
    return {
        **timings,
        "sensor_rows": len(rows),
        "device_count": len(by_device),
        "capability_rows": len(capability_rows),
        "render_errors": render_errors,
        "trust_cache_hits": trust_cache_hits,
        "trust_cache_misses": trust_cache_misses,
    }


@router.get("/metrics", include_in_schema=False)
def grafana_metrics() -> Response:
    """Return aggregate-only Prometheus text for the internal Grafana scraper."""

    now = datetime.now(timezone.utc)
    cutoffs = {
        "1h": (now - timedelta(hours=1)).replace(microsecond=0).isoformat(),
        "24h": (now - timedelta(hours=24)).replace(microsecond=0).isoformat(),
    }
    lines: list[str] = []
    database_available = 0
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        database_available = 1
        _collect_outbound(lines, conn, cutoffs)
        _collect_outbound_protocols(lines, conn, cutoffs)
        _collect_wan(lines, conn, cutoffs)
        _collect_alerts(lines, conn, cutoffs["24h"], now=now)
        _collect_delivery(lines, conn, cutoffs["24h"])
    except Exception as exc:
        # Keep scraping healthy if the database is temporarily unavailable.
        logger.warning("Grafana metrics database unavailable (%s)", type(exc).__name__)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    health_lines: list[str] = []
    _append_header(
        health_lines,
        "nexora_monitoring_database_available",
        "Whether the application can execute a simple database query.",
    )
    health_lines.append(_metric_line("nexora_monitoring_database_available", database_available))
    lines = health_lines + lines
    body = "\n".join(line for line in lines if line) + ("\n" if lines else "")
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/hardware-metrics", include_in_schema=False)
def grafana_hardware_metrics() -> Response:
    """Export per-device hardware series separately from low-cardinality API metrics."""

    scrape_started = time.perf_counter()
    lines: list[str] = []
    conn = None
    scrape_stats: dict[str, Any] = {}
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        scrape_stats = _collect_hardware(lines, conn, datetime.now(timezone.utc))
    except Exception as exc:
        logger.warning("Grafana hardware metrics unavailable (%s)", type(exc).__name__)
        return Response(
            content="hardware metrics temporarily unavailable\n",
            status_code=503,
            media_type="text/plain; charset=utf-8",
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    body = "\n".join(line for line in lines if line) + ("\n" if lines else "")
    body_bytes = len(body.encode("utf-8"))
    logger.info(
        "Grafana hardware metrics scrape sensor_rows=%d devices=%d capabilities=%d "
        "render_errors=%d sensor_query_ms=%.1f sensor_decode_ms=%.1f "
        "source_validation_ms=%.1f trust_cache_hits=%d trust_cache_misses=%d "
        "group_stale_ms=%.1f device_render_ms=%.1f capability_query_ms=%.1f "
        "capability_render_ms=%.1f total_ms=%.1f response_bytes=%d",
        int(scrape_stats.get("sensor_rows", 0)),
        int(scrape_stats.get("device_count", 0)),
        int(scrape_stats.get("capability_rows", 0)),
        int(scrape_stats.get("render_errors", 0)),
        float(scrape_stats.get("sensor_query_ms", 0.0)),
        float(scrape_stats.get("sensor_decode_ms", 0.0)),
        float(scrape_stats.get("source_validation_ms", 0.0)),
        int(scrape_stats.get("trust_cache_hits", 0)),
        int(scrape_stats.get("trust_cache_misses", 0)),
        float(scrape_stats.get("group_and_stale_ms", 0.0)),
        float(scrape_stats.get("device_render_ms", 0.0)),
        float(scrape_stats.get("capability_query_ms", 0.0)),
        float(scrape_stats.get("capability_render_ms", 0.0)),
        (time.perf_counter() - scrape_started) * 1000,
        body_bytes,
    )
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


__all__ = ["router", "grafana_metrics", "grafana_hardware_metrics"]
