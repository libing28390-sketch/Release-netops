"""P1 rollups, maintenance windows, alert workflow, link groups and reports."""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import _USE_PG, get_db_connection


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _zone(value: Any) -> ZoneInfo | None:
    name = str(value or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    rank = max(0, min(len(values) - 1, int(math.ceil(percentile * len(values))) - 1))
    return values[rank]


def _bucket(dt: datetime, step_seconds: int) -> datetime:
    timestamp = int(dt.timestamp()) // step_seconds * step_seconds
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0)


def _sample_table() -> str:
    return "wan_link_samples_1m_partitioned" if _USE_PG else "wan_link_samples_1m"


def ensure_wan_partitions_once() -> dict[str, Any]:
    """Provision a safe rolling window of PostgreSQL monthly partitions."""
    if not _USE_PG:
        return {"created": 0, "skipped": True}
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    conn = get_db_connection()
    created = 0
    try:
        # Multiple API/scheduler instances may wake up at the same minute.
        # Keep partition DDL mutually exclusive without relying on an
        # application-local lock.  The advisory lock is transaction-scoped
        # and therefore released by the commit/rollback below.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("nexora:wan:partitions",))
        for offset in range(-1, 4):
            month_index = now.year * 12 + now.month - 1 + offset
            year, month0 = divmod(month_index, 12)
            month = month0 + 1
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
            name = f"wan_link_samples_1m_{year}{month:02d}"
            conn.execute(f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF wan_link_samples_1m_partitioned FOR VALUES FROM ('{start.isoformat()}') TO ('{next_month.isoformat()}')")
            created += 1
        conn.commit()
        return {"created": created, "skipped": False}
    finally:
        conn.close()


def _quality_flags(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("quality_flags")
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _valid_sample(row: dict[str, Any]) -> bool:
    if str(row.get("collection_status") or "") != "success":
        return False
    flags = _quality_flags(row)
    # Direction-specific flags (download_counter_reset, upload_counter_missing
    # and friends) are the values emitted by the WAN collector.  Checking only
    # the old generic names silently let invalid samples into long-term
    # rollups.  Counter wraps remain valid deltas and are intentionally not in
    # this rejection set.
    invalid_markers = (
        "interval_abnormal",
        "counter_reset",
        "counter_missing",
        "counter_width_unknown",
        "counter_ambiguous",
        "counter_invalid",
        "device_restart",
        "invalid_spike",
    )
    return not any(
        bool(value) and any(marker in str(key).lower() for marker in invalid_markers)
        for key, value in flags.items()
    )


def _rollup_table(
    table: str,
    step_seconds: int,
    lookback_days: int = 35,
    *,
    source_table: str | None = None,
    source_step_seconds: int = 60,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    conn = get_db_connection()
    try:
        source = source_table or _sample_table()
        time_column = "bucket_start" if source_table else "sampled_at"
        rows = [dict(row) for row in conn.execute(
            f"SELECT * FROM {source} WHERE {time_column} >= ? ORDER BY {time_column} ASC",
            (cutoff.isoformat(),),
        ).fetchall()]
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            sampled = _parse(row.get(time_column))
            if not sampled:
                continue
            key = (str(row["link_id"]), _bucket(sampled, step_seconds).isoformat())
            buckets.setdefault(key, []).append(row)
        for (link_id, bucket_start), points in buckets.items():
            rollup_source = source_table is not None

            def nums(raw_key: str, rollup_key: str) -> list[float]:
                key = rollup_key if rollup_source else raw_key
                return [float(point[key]) for point in points if point.get(key) is not None and (rollup_source or _valid_sample(point))]

            download = nums("download_bps", "avg_download_bps")
            upload = nums("upload_bps", "avg_upload_bps")
            download_util = nums("download_util_pct", "avg_download_util_pct")
            upload_util = nums("upload_util_pct", "avg_upload_util_pct")
            in_error_rate = nums("in_error_rate", "avg_in_error_rate")
            out_error_rate = nums("out_error_rate", "avg_out_error_rate")
            in_discard_rate = nums("in_discard_rate", "avg_in_discard_rate")
            out_discard_rate = nums("out_discard_rate", "avg_out_discard_rate")
            p95_download = nums("download_bps", "p95_download_bps") if rollup_source else download
            p95_upload = nums("upload_bps", "p95_upload_bps") if rollup_source else upload
            valid_points = [point for point in points if _valid_sample(point)] if not rollup_source else [point for point in points if float(point.get("coverage_pct") or 0) >= 80]
            if rollup_source:
                sample_count = sum(int(point.get("sample_count") or 0) for point in valid_points)
                expected = max(1, sum(max(1, round(source_step_seconds / 60)) for point in points))
                successful = sum(max(0, int(point.get("sample_count") or 0)) * min(100.0, max(0.0, float(point.get("coverage_pct") or 0))) / 100 for point in points)
            else:
                sample_count = len(points)
                expected = max(1, round(step_seconds / 60))
                successful = sum(1 for point in valid_points)
            flags = {"invalid_samples": max(0, sample_count - int(round(successful)))}

            def total(raw_key: str, rollup_key: str) -> int:
                key = rollup_key if rollup_source else raw_key
                return sum(int(point[key]) for point in valid_points if point.get(key) is not None)

            def maximum(values: list[float]) -> int | None:
                return round(max(values)) if values else None

            def high_load_minutes(threshold: float) -> int:
                total_minutes = 0
                for point in (valid_points if rollup_source else points):
                    if rollup_source:
                        util = max(float(point.get("p95_download_util_pct") or point.get("max_download_util_pct") or 0), float(point.get("p95_upload_util_pct") or point.get("max_upload_util_pct") or 0))
                        duration = max(1, round(source_step_seconds / 60))
                    else:
                        util = max(float(point.get("download_util_pct") or 0), float(point.get("upload_util_pct") or 0))
                        duration = 1
                    if util >= threshold:
                        total_minutes += duration
                return total_minutes

            values = (
                link_id, bucket_start, sample_count, round(min(100.0, successful / expected * 100), 2),
                round(sum(download) / len(download)) if download else None,
                round(sum(upload) / len(upload)) if upload else None,
                maximum(download), maximum(upload), round(_percentile(p95_download, 0.95)) if p95_download else None,
                round(_percentile(p95_upload, 0.95)) if p95_upload else None,
                round(sum(download_util) / len(download_util), 3) if download_util else None,
                round(sum(upload_util) / len(upload_util), 3) if upload_util else None,
                round(max(download_util), 3) if download_util else None,
                round(max(upload_util), 3) if upload_util else None,
                round(_percentile(download_util, 0.95), 3) if download_util else None,
                round(_percentile(upload_util, 0.95), 3) if upload_util else None,
                round(sum(in_error_rate) / len(in_error_rate), 6) if in_error_rate else None,
                round(sum(out_error_rate) / len(out_error_rate), 6) if out_error_rate else None,
                round(sum(in_discard_rate) / len(in_discard_rate), 6) if in_discard_rate else None,
                round(sum(out_discard_rate) / len(out_discard_rate), 6) if out_discard_rate else None,
                int(round(successful)) if rollup_source else len(valid_points), high_load_minutes(70), high_load_minutes(85), high_load_minutes(95),
                total("in_error_delta", "in_error_total"), total("out_error_delta", "out_error_total"),
                total("in_discard_delta", "in_discard_total"), total("out_discard_delta", "out_discard_total"),
                json.dumps(flags), _now(),
            )
            conn.execute(
                f"""INSERT INTO {table} (
                    link_id, bucket_start, sample_count, coverage_pct, avg_download_bps, avg_upload_bps,
                    max_download_bps, max_upload_bps, p95_download_bps, p95_upload_bps,
                    avg_download_util_pct, avg_upload_util_pct, max_download_util_pct, max_upload_util_pct,
                    p95_download_util_pct, p95_upload_util_pct,
                    avg_in_error_rate, avg_out_error_rate, avg_in_discard_rate, avg_out_discard_rate,
                    valid_sample_count, high_70_minutes, high_85_minutes, high_95_minutes,
                    in_error_total, out_error_total, in_discard_total, out_discard_total, quality_flags, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link_id, bucket_start) DO UPDATE SET
                    sample_count=excluded.sample_count, coverage_pct=excluded.coverage_pct,
                    avg_download_bps=excluded.avg_download_bps, avg_upload_bps=excluded.avg_upload_bps,
                    max_download_bps=excluded.max_download_bps, max_upload_bps=excluded.max_upload_bps,
                    p95_download_bps=excluded.p95_download_bps, p95_upload_bps=excluded.p95_upload_bps,
                    avg_download_util_pct=excluded.avg_download_util_pct, avg_upload_util_pct=excluded.avg_upload_util_pct,
                    max_download_util_pct=excluded.max_download_util_pct, max_upload_util_pct=excluded.max_upload_util_pct,
                    p95_download_util_pct=excluded.p95_download_util_pct, p95_upload_util_pct=excluded.p95_upload_util_pct,
                    avg_in_error_rate=excluded.avg_in_error_rate, avg_out_error_rate=excluded.avg_out_error_rate,
                    avg_in_discard_rate=excluded.avg_in_discard_rate, avg_out_discard_rate=excluded.avg_out_discard_rate,
                    valid_sample_count=excluded.valid_sample_count, high_70_minutes=excluded.high_70_minutes,
                    high_85_minutes=excluded.high_85_minutes, high_95_minutes=excluded.high_95_minutes,
                    in_error_total=excluded.in_error_total, out_error_total=excluded.out_error_total,
                    in_discard_total=excluded.in_discard_total, out_discard_total=excluded.out_discard_total,
                    quality_flags=excluded.quality_flags, updated_at=excluded.updated_at""",
                values,
            )
        conn.commit()
        return {"table": table, "buckets": len(buckets), "samples": len(rows)}
    finally:
        conn.close()


def rollup_wan_samples_once() -> dict[str, Any]:
    return {
        "five_min": _rollup_table("wan_link_samples_5m", 300, 35),
        # Build longer windows from the prior rollup so raw 1-minute retention
        # can remain bounded without silently stopping long-term aggregation.
        "hourly": _rollup_table("wan_link_samples_1h", 3600, 190, source_table="wan_link_samples_5m", source_step_seconds=300),
        "daily": _rollup_table("wan_link_samples_daily", 86400, 740, source_table="wan_link_samples_1h", source_step_seconds=3600),
    }


def apply_wan_retention_once() -> dict[str, int]:
    conn = get_db_connection()
    run_id = f"wan-retention-{uuid.uuid4().hex}"
    started = _now()
    policy: dict[str, Any] = {}
    policy_json = "{}"
    try:
        policy = dict(conn.execute("SELECT * FROM wan_retention_policies WHERE id = 'default'").fetchone() or {})
        # PostgreSQL returns timestamp columns as ``datetime`` objects while
        # SQLite returns strings.  Retention runs must be auditable on both
        # backends, so normalize the policy payload before persisting JSON.
        policy_json = json.dumps(policy, default=str)
        removed: dict[str, int] = {}
        for table, column, days in (
            (_sample_table(), "sampled_at", policy.get("raw_days", 30)),
            ("wan_link_samples_5m", "bucket_start", policy.get("five_min_days", 180)),
            ("wan_link_samples_1h", "bucket_start", policy.get("hourly_days", 730)),
            ("wan_link_samples_daily", "bucket_start", policy.get("daily_days", 3650)),
        ):
            cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
            cur = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            removed[table] = int(getattr(cur, "rowcount", 0) or 0)
        if _USE_PG:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=int(policy.get("raw_days", 30)))
            partition_rows = conn.execute("""SELECT child.relname FROM pg_inherits JOIN pg_class child ON child.oid = pg_inherits.inhrelid JOIN pg_class parent ON parent.oid = pg_inherits.inhparent WHERE parent.relname = 'wan_link_samples_1m_partitioned'""").fetchall()
            dropped = 0
            for row in partition_rows:
                name = str(row[0])
                match = re.fullmatch(r"wan_link_samples_1m_(\d{4})(\d{2})", name)
                if not match:
                    continue
                year, month = int(match.group(1)), int(match.group(2))
                next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
                if next_month <= cutoff_dt:
                    conn.execute(f"DROP TABLE IF EXISTS {name}")
                    dropped += 1
            removed["raw_partitions"] = dropped
        conn.execute(
            "INSERT INTO wan_retention_runs (id, started_at, completed_at, status, policy_json, deleted_json) VALUES (?, ?, ?, 'completed', ?, ?)",
            (run_id, started, _now(), policy_json, json.dumps(removed)),
        )
        conn.commit()
        return removed
    except Exception as exc:
        conn.rollback()
        try:
            conn.execute(
                "INSERT INTO wan_retention_runs (id, started_at, completed_at, status, policy_json, deleted_json, error_message) VALUES (?, ?, ?, 'failed', ?, '{}', ?)",
                (run_id, started, _now(), policy_json, str(exc)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def is_wan_link_in_maintenance(conn, link_id: str, site_id: str, now: str | None = None) -> bool:
    current = _parse(now or _now()) or datetime.now(timezone.utc)
    device_row = conn.execute("SELECT device_id FROM wan_links WHERE id = ?", (link_id,)).fetchone()
    device_id = str(device_row[0]) if device_row else ""
    group_ids = {str(row[0]) for row in conn.execute("SELECT group_id FROM wan_link_group_members WHERE link_id = ?", (link_id,)).fetchall()}
    windows = conn.execute("SELECT * FROM wan_maintenance_windows WHERE enabled = TRUE AND deleted_at IS NULL").fetchall()
    for row in windows:
        item = dict(row)
        if item.get("link_id") not in {"", link_id} and item.get("site_id") not in {"", site_id} and item.get("device_id") not in {"", device_id} and item.get("link_group_id") not in group_ids:
            continue
        start, end = _parse(item.get("starts_at")), _parse(item.get("ends_at"))
        if not start or not end:
            continue
        recurrence = str(item.get("recurrence") or "once").lower()
        if recurrence == "once":
            if start <= current <= end:
                return True
            continue
        local_zone = _zone(item.get("timezone"))
        if local_zone is None:
            # An invalid timezone must not silently widen a maintenance
            # window.  The write API rejects it; this guards legacy rows.
            continue
        local_current = current.astimezone(local_zone)
        local_start = start.astimezone(local_zone)
        duration = end - start
        if duration.total_seconds() <= 0 or local_current < local_start:
            continue
        if recurrence == "daily":
            occurrence = local_start + timedelta(days=(local_current.date() - local_start.date()).days)
        elif recurrence == "weekly":
            occurrence = local_start + timedelta(weeks=(local_current.date() - local_start.date()).days // 7)
        elif recurrence == "monthly":
            months = (local_current.year - local_start.year) * 12 + local_current.month - local_start.month
            month_index = local_start.year * 12 + local_start.month - 1 + max(0, months)
            year, month0 = divmod(month_index, 12)
            month_start = datetime(year, month0 + 1, 1, tzinfo=local_zone)
            next_month_start = (month_start + timedelta(days=32)).replace(day=1)
            day = min(local_start.day, (next_month_start - timedelta(days=1)).day)
            occurrence = month_start.replace(day=day, hour=local_start.hour, minute=local_start.minute, second=local_start.second, microsecond=0)
        else:
            continue
        if occurrence <= local_current <= occurrence + duration:
            return True
    return False


def update_wan_alert_workflow(event_id: str, action: str, actor: dict[str, Any]) -> dict[str, Any] | None:
    if action not in {"acknowledge", "close"}:
        raise ValueError("Unsupported alert workflow action")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM wan_alert_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        before = dict(row)
        now = _now()
        note = str(actor.get("note") or "").strip()
        details = before.get("details") if isinstance(before.get("details"), dict) else _parse_json_object(before.get("details"))
        if note:
            details["workflow_note"] = note
        if action == "acknowledge":
            conn.execute("UPDATE wan_alert_events SET status = CASE WHEN status = 'firing' THEN 'acknowledged' ELSE status END, acknowledged_at = ?, acknowledged_by = ?, details = ?, updated_at = ? WHERE id = ?", (now, str(actor.get("username") or actor.get("id") or ""), json.dumps(details, ensure_ascii=False), now, event_id))
        else:
            conn.execute("UPDATE wan_alert_events SET status = 'closed', closed_at = ?, closed_by = ?, details = ?, updated_at = ? WHERE id = ?", (now, str(actor.get("username") or actor.get("id") or ""), json.dumps(details, ensure_ascii=False), now, event_id))
        after_row = conn.execute("SELECT * FROM wan_alert_events WHERE id = ?", (event_id,)).fetchone()
        after = dict(after_row)
        conn.execute(
            "INSERT INTO wan_alert_event_audit (id, event_id, action, actor_id, actor_name, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), event_id, action, str(actor.get("id") or ""), str(actor.get("username") or ""), json.dumps(before), json.dumps(after), now),
        )
        conn.commit()
        return after
    finally:
        conn.close()


def list_wan_maintenance_windows() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM wan_maintenance_windows WHERE deleted_at IS NULL ORDER BY starts_at DESC").fetchall()]
    finally:
        conn.close()


def upsert_wan_maintenance_window(payload: dict[str, Any], actor: dict[str, Any], window_id: str | None = None) -> dict[str, Any]:
    required = ("name", "starts_at", "ends_at")
    if any(not str(payload.get(key) or "").strip() for key in required):
        raise ValueError("name, starts_at and ends_at are required")
    start, end = _parse(payload["starts_at"]), _parse(payload["ends_at"])
    if not start or not end or end <= start:
        raise ValueError("maintenance window time range is invalid")
    timezone_name = str(payload.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    if _zone(timezone_name) is None:
        raise ValueError("maintenance timezone is invalid")
    recurrence = str(payload.get("recurrence") or "once").strip().lower()
    if recurrence not in {"once", "daily", "weekly", "monthly"}:
        raise ValueError("maintenance recurrence is invalid")
    conn = get_db_connection()
    try:
        now = _now()
        item_id = window_id or str(payload.get("id") or f"wan-maint-{uuid.uuid4().hex}")
        scope_checks = (
            ("link_id", "wan_links"),
            ("device_id", "devices"),
            ("link_group_id", "wan_link_groups"),
            ("site_id", "sites"),
        )
        for field, table in scope_checks:
            scope_id = str(payload.get(field) or "").strip()
            if scope_id and not conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (scope_id,)).fetchone():
                raise ValueError(f"maintenance scope {field} does not exist")
        values = (item_id, str(payload.get("site_id") or ""), str(payload.get("link_id") or ""), str(payload.get("device_id") or ""), str(payload.get("link_group_id") or ""), str(payload.get("name") or ""), start.isoformat(), end.isoformat(), timezone_name, recurrence, str(payload.get("reason") or ""), bool(payload.get("enabled", True)), str(actor.get("username") or actor.get("id") or ""), now, now)
        conn.execute("""INSERT INTO wan_maintenance_windows (id, site_id, link_id, device_id, link_group_id, name, starts_at, ends_at, timezone, recurrence, reason, enabled, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET site_id=excluded.site_id, link_id=excluded.link_id, device_id=excluded.device_id, link_group_id=excluded.link_group_id, name=excluded.name, starts_at=excluded.starts_at, ends_at=excluded.ends_at, timezone=excluded.timezone, recurrence=excluded.recurrence, reason=excluded.reason, enabled=excluded.enabled, updated_at=excluded.updated_at""", values)
        conn.commit()
        return dict(conn.execute("SELECT * FROM wan_maintenance_windows WHERE id = ?", (item_id,)).fetchone())
    finally:
        conn.close()


def delete_wan_maintenance_window(window_id: str) -> bool:
    conn = get_db_connection()
    try:
        now = _now()
        cur = conn.execute("UPDATE wan_maintenance_windows SET enabled = FALSE, deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL", (now, now, window_id))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def generate_wan_report(report_type: str, period_start: str, period_end: str, actor: dict[str, Any]) -> dict[str, Any]:
    if report_type not in {"daily", "weekly", "monthly"}:
        raise ValueError("report_type must be daily, weekly or monthly")
    start, end = _parse(period_start), _parse(period_end)
    if not start or not end or end <= start:
        raise ValueError("report period is invalid")
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT result_json FROM wan_report_runs WHERE report_type = ? AND period_start = ? AND period_end = ? AND status = 'completed' ORDER BY created_at DESC LIMIT 1",
            (report_type, start.isoformat(), end.isoformat()),
        ).fetchone()
        if existing:
            stored = existing[0] if not isinstance(existing, dict) else existing.get("result_json")
            if isinstance(stored, dict):
                return stored
            try:
                return json.loads(stored or "{}")
            except (TypeError, ValueError):
                pass
        report_id, now = f"wan-report-{uuid.uuid4().hex}", _now()
        conn.execute("INSERT INTO wan_report_runs (id, report_type, period_start, period_end, status, scope_json, result_json, generated_by, created_at, report_version, data_cutoff_at) VALUES (?, ?, ?, ?, 'running', '{}', '{}', ?, ?, 'wan-report-v2', ?)", (report_id, report_type, start.isoformat(), end.isoformat(), str(actor.get("username") or actor.get("id") or ""), now, now))
        rows = [dict(row) for row in conn.execute("SELECT * FROM wan_link_samples_1h WHERE bucket_start >= ? AND bucket_start < ?", (start.isoformat(), end.isoformat())).fetchall()]
        events = [dict(row) for row in conn.execute("SELECT severity, status, COUNT(*) AS count FROM wan_alert_events WHERE started_at >= ? AND started_at < ? GROUP BY severity, status", (start.isoformat(), end.isoformat())).fetchall()]
        links = [dict(row) for row in conn.execute("SELECT id, link_name, provider, site_name FROM wan_links ORDER BY site_name, link_name").fetchall()]
        by_link: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_link.setdefault(str(row.get("link_id")), []).append(row)
        link_metrics = []
        for link in links:
            points = by_link.get(str(link["id"]), [])
            util = [max(float(point.get("p95_download_util_pct") or 0), float(point.get("p95_upload_util_pct") or 0)) for point in points]
            link_metrics.append({
                **link,
                "sample_count": sum(int(point.get("sample_count") or 0) for point in points),
                "coverage_pct": round(sum(float(point.get("coverage_pct") or 0) for point in points) / len(points), 2) if points else 0,
                "p95_utilization_pct": round(_percentile(util, 0.95), 3) if util else None,
                "peak_utilization_pct": round(max(util), 3) if util else None,
                "high_load_hours": sum(1 for value in util if value >= 85),
                "critical_load_hours": sum(1 for value in util if value >= 95),
            })
        probe_summary = []
        binding_rows = conn.execute("SELECT link_id, target_id FROM wan_probe_bindings WHERE enabled = TRUE").fetchall()
        for binding in binding_rows:
            total = int(conn.execute("SELECT COUNT(*) FROM outbound_probe_results WHERE target_id = ? AND sampled_at >= ? AND sampled_at < ?", (binding[1], start.isoformat(), end.isoformat())).fetchone()[0])
            success = int(conn.execute("SELECT COUNT(*) FROM outbound_probe_results WHERE target_id = ? AND success = TRUE AND sampled_at >= ? AND sampled_at < ?", (binding[1], start.isoformat(), end.isoformat())).fetchone()[0])
            probe_summary.append({"link_id": binding[0], "target_id": binding[1], "sample_count": total, "availability_pct": round(success / total * 100, 2) if total else None})
        result = {"report_id": report_id, "report_type": report_type, "period_start": start.isoformat(), "period_end": end.isoformat(), "data_cutoff_at": now, "report_version": "wan-report-v2", "links": links, "link_metrics": link_metrics, "rollups": rows, "alerts": events, "probe_availability": probe_summary, "generated_at": now}
        conn.execute("UPDATE wan_report_runs SET status = 'completed', result_json = ?, completed_at = ? WHERE id = ?", (json.dumps(result, default=str), _now(), report_id))
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _decode_report(row: Any) -> dict[str, Any]:
    item = dict(row)
    raw = item.get("result_json")
    if isinstance(raw, dict):
        item["result"] = raw
    else:
        try:
            item["result"] = json.loads(raw or "{}")
        except (TypeError, ValueError):
            item["result"] = {}
    return item


def list_wan_reports(*, report_type: str = "", limit: int = 20) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        clauses, params = [], []
        if report_type:
            clauses.append("report_type = ?")
            params.append(report_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(f"SELECT * FROM wan_report_runs {where} ORDER BY created_at DESC LIMIT ?", tuple(params + [max(1, min(100, int(limit)))]),).fetchall()
        return [_decode_report(row) for row in rows]
    finally:
        conn.close()


def get_wan_report(report_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM wan_report_runs WHERE id = ?", (report_id,)).fetchone()
        return _decode_report(row) if row else None
    finally:
        conn.close()


def mark_wan_report_exported(report_id: str, actor: dict[str, Any]) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        now = _now()
        cur = conn.execute("UPDATE wan_report_runs SET exported_at = ?, exported_by = ? WHERE id = ? AND status = 'completed'", (now, str(actor.get("username") or actor.get("id") or ""), report_id))
        if not cur.rowcount:
            return None
        conn.commit()
        row = conn.execute("SELECT * FROM wan_report_runs WHERE id = ?", (report_id,)).fetchone()
        return _decode_report(row) if row else None
    finally:
        conn.close()


def list_wan_link_groups() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        groups = [dict(row) for row in conn.execute("SELECT * FROM wan_link_groups ORDER BY group_name").fetchall()]
        for group in groups:
            members = [dict(row) for row in conn.execute("""SELECT m.*, l.link_name, l.link_role, l.site_name, l.provider,
                    l.contracted_download_bps, l.contracted_upload_bps,
                    c.health_status, c.oper_status, c.download_bps, c.upload_bps, c.sampled_at
                    FROM wan_link_group_members m JOIN wan_links l ON l.id = m.link_id
                    LEFT JOIN wan_link_current_status c ON c.link_id = l.id
                    WHERE m.group_id = ? ORDER BY m.priority, l.link_name""", (group["id"],)).fetchall()]
            primary = [item for item in members if item.get("role") == "primary"]
            backups = [item for item in members if item.get("role") == "backup"]
            switched = bool(primary and backups and all(item.get("health_status") in {"critical", "unavailable", "unknown"} for item in primary) and any(item.get("health_status") == "healthy" and float(item.get("download_bps") or 0) + float(item.get("upload_bps") or 0) > 0 for item in backups))
            group["members"] = members
            group["health_status"] = "healthy" if members and all(item.get("health_status") == "healthy" for item in members if item.get("health_status")) else "degraded" if members else "unknown"
            group["switch_status"] = "switched" if switched else "standby"
            group["total_download_bps"] = sum(int(item.get("contracted_download_bps") or 0) for item in members)
            group["total_upload_bps"] = sum(int(item.get("contracted_upload_bps") or 0) for item in members)
        return groups
    finally:
        conn.close()


def upsert_wan_link_group(payload: dict[str, Any], actor: dict[str, Any], group_id: str | None = None) -> dict[str, Any]:
    name = str(payload.get("group_name") or "").strip()
    if not name:
        raise ValueError("group_name is required")
    mode = str(payload.get("mode") or "primary_backup")
    if mode not in {"primary_backup", "load_balanced"}:
        raise ValueError("mode must be primary_backup or load_balanced")
    members = payload.get("members") or []
    if not isinstance(members, list):
        raise ValueError("members must be a list")
    conn = get_db_connection()
    try:
        now, item_id = _now(), group_id or str(payload.get("id") or f"wan-group-{uuid.uuid4().hex}")
        group_site_id = str(payload.get("site_id") or "").strip()
        group_provider = str(payload.get("provider") or "").strip()
        seen_links: set[str] = set()
        primary_count = 0
        for member in members:
            link_id = str(member.get("link_id") or "").strip()
            if not link_id or link_id in seen_links:
                raise ValueError("A link may appear only once in a group")
            seen_links.add(link_id)
            row = conn.execute("SELECT site_id, provider FROM wan_links WHERE id = ?", (link_id,)).fetchone()
            if not row:
                raise ValueError("Every group member must reference an existing WAN link")
            if group_site_id and str(row[0] or "") not in {"", group_site_id}:
                raise ValueError("Every group member must belong to the selected site")
            if group_provider and str(row[1] or "") not in {"", group_provider}:
                raise ValueError("Every group member must use the selected provider")
            role = str(member.get("role") or "primary")
            if role not in {"primary", "backup", "load_balanced"}:
                raise ValueError("Invalid group member role")
            if mode == "primary_backup" and role == "primary":
                primary_count += 1
        if mode == "primary_backup" and primary_count > 1:
            raise ValueError("primary_backup groups may contain only one primary link")
        conn.execute("INSERT INTO wan_link_groups (id, group_name, mode, site_id, provider, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET group_name=excluded.group_name, mode=excluded.mode, site_id=excluded.site_id, provider=excluded.provider, enabled=excluded.enabled, updated_at=excluded.updated_at", (item_id, name, mode, str(payload.get("site_id") or ""), str(payload.get("provider") or ""), bool(payload.get("enabled", True)), now, now))
        conn.execute("DELETE FROM wan_link_group_members WHERE group_id = ?", (item_id,))
        for member in members:
            link_id = str(member.get("link_id") or "")
            if not link_id or not conn.execute("SELECT 1 FROM wan_links WHERE id = ?", (link_id,)).fetchone():
                raise ValueError("Every group member must reference an existing WAN link")
            role = str(member.get("role") or "primary")
            if role not in {"primary", "backup", "load_balanced"}:
                raise ValueError("Invalid group member role")
            conn.execute("INSERT INTO wan_link_group_members (group_id, link_id, role, priority, weight, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(group_id, link_id) DO UPDATE SET role=excluded.role, priority=excluded.priority, weight=excluded.weight, updated_at=excluded.updated_at", (item_id, link_id, role, int(member.get("priority") or 100), int(member.get("weight") or 1), now, now))
        conn.commit()
        return next(group for group in list_wan_link_groups() if group["id"] == item_id)
    finally:
        conn.close()
