"""Deterministic P2 correlation, baselines, capacity evidence and cockpit data."""

from __future__ import annotations

import json
import ipaddress
import math
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database import _USE_PG, get_db_connection


RULE_VERSION = "wan-correlation-v1"


def _sample_table() -> str:
    return "wan_link_samples_1m_partitioned" if _USE_PG else "wan_link_samples_1m"


def _now() -> str:
    # Correlation recomputation can run more than once in the same second.
    # Retaining microseconds lets the recovery pass distinguish an event
    # refreshed by the current run from one left over from the prior run.
    return datetime.now(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def upsert_probe_binding(payload: dict[str, Any], actor: dict[str, Any], binding_id: str | None = None) -> dict[str, Any]:
    link_id, target_id = str(payload.get("link_id") or "").strip(), str(payload.get("target_id") or "").strip()
    if not link_id or not target_id:
        raise ValueError("link_id and target_id are required")
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM wan_links WHERE id = ?", (link_id,)).fetchone():
            raise ValueError("WAN link does not exist")
        target = conn.execute("SELECT id, is_active FROM outbound_probe_targets WHERE id = ?", (target_id,)).fetchone()
        if not target:
            raise ValueError("Probe target does not exist")
        if not bool(target[1]):
            raise ValueError("Probe target is disabled")
        route_mode = str(payload.get("route_mode") or "default").strip().lower()
        if route_mode not in {"default", "source_ip"}:
            raise ValueError("route_mode must be default or source_ip")
        source_ip = str(payload.get("source_ip") or "").strip()
        if route_mode == "source_ip":
            try:
                ipaddress.ip_address(source_ip)
            except ValueError as exc:
                raise ValueError("source_ip must be a valid IP address when route_mode is source_ip") from exc
        item_id = binding_id or str(payload.get("id") or f"wan-binding-{uuid.uuid4().hex}")
        now = _now()
        before_row = conn.execute("SELECT * FROM wan_probe_bindings WHERE id = ?", (item_id,)).fetchone()
        route_evidence = {"mode": route_mode, "source_ip_configured": bool(source_ip), "evidence_status": "verified_source_ip" if route_mode == "source_ip" else "insufficient_default_route"}
        conn.execute("""INSERT INTO wan_probe_bindings (id, link_id, target_id, route_mode, source_ip, priority, enabled, created_by, created_at, updated_at, route_evidence_json, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET link_id=excluded.link_id, target_id=excluded.target_id, route_mode=excluded.route_mode, source_ip=excluded.source_ip, priority=excluded.priority, enabled=excluded.enabled, updated_at=excluded.updated_at, route_evidence_json=excluded.route_evidence_json, updated_by=excluded.updated_by""", (item_id, link_id, target_id, route_mode, source_ip, int(payload.get("priority") or 100), bool(payload.get("enabled", True)), str(actor.get("username") or actor.get("id") or ""), now, now, json.dumps(route_evidence), str(actor.get("username") or actor.get("id") or "")))
        after_row = conn.execute("SELECT * FROM wan_probe_bindings WHERE id = ?", (item_id,)).fetchone()
        conn.execute("INSERT INTO wan_probe_binding_audit (id, binding_id, action, actor_id, actor_name, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"wan-binding-audit-{uuid.uuid4().hex}", item_id, "update" if before_row else "create", str(actor.get("id") or ""), str(actor.get("username") or ""), json.dumps(dict(before_row) if before_row else {}, default=str), json.dumps(dict(after_row) if after_row else {}, default=str), now))
        conn.commit()
        return dict(after_row)
    finally:
        conn.close()


def list_probe_bindings(link_id: str = "", target_id: str = "") -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        clauses, params = [], []
        if link_id:
            clauses.append("b.link_id = ?")
            params.append(link_id)
        if target_id:
            clauses.append("b.target_id = ?")
            params.append(target_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        result = []
        for row in conn.execute(f"""SELECT b.*, l.link_name, l.site_name, t.target_name, t.host, t.probe_type FROM wan_probe_bindings b JOIN wan_links l ON l.id = b.link_id JOIN outbound_probe_targets t ON t.id = b.target_id {where} ORDER BY l.site_name, l.link_name, b.priority""", tuple(params)).fetchall():
            item = dict(row)
            try:
                item["route_evidence"] = json.loads(item.pop("route_evidence_json") or "{}")
            except (TypeError, ValueError):
                item["route_evidence"] = {}
            result.append(item)
        return result
    finally:
        conn.close()


def _latest_target_results(conn, target_ids: list[str], cutoff: str) -> list[dict[str, Any]]:
    if not target_ids:
        return []
    placeholders = ",".join("?" for _ in target_ids)
    rows = conn.execute(f"SELECT r.* FROM outbound_probe_results r JOIN (SELECT target_id, MAX(sampled_at) AS latest FROM outbound_probe_results WHERE target_id IN ({placeholders}) AND sampled_at >= ? GROUP BY target_id) x ON x.target_id = r.target_id AND x.latest = r.sampled_at", tuple(target_ids + [cutoff])).fetchall()
    return [dict(row) for row in rows]


def delete_probe_binding(binding_id: str, actor: dict[str, Any]) -> bool:
    conn = get_db_connection()
    try:
        before = conn.execute("SELECT * FROM wan_probe_bindings WHERE id = ?", (binding_id,)).fetchone()
        if not before:
            return False
        now = _now()
        conn.execute("DELETE FROM wan_probe_bindings WHERE id = ?", (binding_id,))
        conn.execute("INSERT INTO wan_probe_binding_audit (id, binding_id, action, actor_id, actor_name, before_json, after_json, created_at) VALUES (?, ?, 'delete', ?, ?, ?, '{}', ?)", (f"wan-binding-audit-{uuid.uuid4().hex}", binding_id, str(actor.get("id") or ""), str(actor.get("username") or ""), json.dumps(dict(before), default=str), now))
        conn.commit()
        return True
    finally:
        conn.close()


def _open_or_update_correlation(conn, *, group: str, code: str, title: str, summary: str, severity: str, confidence: float, scope: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
    now = _now()
    row = conn.execute("SELECT * FROM wan_correlation_events WHERE correlation_group = ? AND root_cause_code = ? AND status IN ('open', 'acknowledged')", (group, code)).fetchone()
    event_id = str(row["id"]) if row else f"wan-correlation-{uuid.uuid4().hex}"
    if row:
        conn.execute("UPDATE wan_correlation_events SET severity = ?, confidence = ?, summary = ?, scope_json = ?, last_seen_at = ?, updated_at = ? WHERE id = ?", (severity, confidence, summary, json.dumps(scope, default=str), now, now, event_id))
    else:
        conn.execute("INSERT INTO wan_correlation_events (id, correlation_group, root_cause_code, severity, status, confidence, title, summary, scope_json, rule_version, starts_at, last_seen_at, created_at, updated_at) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)", (event_id, group, code, severity, confidence, title, summary, json.dumps(scope, default=str), RULE_VERSION, now, now, now, now))
    for item in evidence:
        conn.execute("INSERT INTO wan_correlation_evidence (id, event_id, source_type, source_id, observed_at, metric, metric_value, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (f"wan-evidence-{uuid.uuid4().hex}", event_id, item.get("source_type", "unknown"), str(item.get("source_id") or ""), item.get("observed_at") or now, str(item.get("metric") or ""), item.get("metric_value"), json.dumps(item.get("details") or {}, default=str), now))


def recompute_wan_correlations() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        run_started = _now()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        links = [dict(row) for row in conn.execute("SELECT * FROM wan_links WHERE enabled = TRUE").fetchall()]
        created = 0
        for link in links:
            current = dict(conn.execute("SELECT * FROM wan_link_current_status WHERE link_id = ?", (link["id"],)).fetchone() or {})
            latest_sample = dict(conn.execute(f"SELECT * FROM {_sample_table()} WHERE link_id = ? ORDER BY sampled_at DESC LIMIT 1", (link["id"],)).fetchone() or {})
            bindings = [dict(row) for row in conn.execute("SELECT * FROM wan_probe_bindings WHERE link_id = ? AND enabled = TRUE", (link["id"],)).fetchall()]
            target_results = _latest_target_results(conn, [str(item["target_id"]) for item in bindings], cutoff)
            failed = [item for item in target_results if not bool(item.get("success"))]
            successful = [item for item in target_results if bool(item.get("success"))]
            scope = {"link_id": link["id"], "site_id": link.get("site_id"), "target_ids": [item["target_id"] for item in bindings]}
            scope["route_evidence"] = [_json_object(item.get("route_evidence_json")) for item in bindings]
            if current.get("collection_status") in {"timeout", "auth_failed", "device_unreachable", "failed", "interface_not_found", "not_configured"} or current.get("health_status") == "unavailable":
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="egress_device_fault", title="出口设备采集异常", summary="出口设备或 SNMP 采集失败，链路数据不可作为正常流量证据。", severity="critical", confidence=0.95, scope=scope, evidence=[{"source_type": "wan_current_status", "source_id": link["id"], "metric": "collection_status", "metric_value": None, "details": current}])
                created += 1
            elif current.get("oper_status") == "down":
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="egress_interface_fault", title="出口接口 Down", summary="采集成功且出口接口为 Down；探测失败作为同时间窗的增强证据保留。", severity="critical", confidence=0.9, scope={**scope, "failed_target_ids": [item.get("target_id") for item in failed]}, evidence=[{"source_type": "wan_current_status", "source_id": link["id"], "metric": "oper_status", "details": current}, *[{"source_type": "probe_result", "source_id": item.get("id"), "metric": "success", "details": item} for item in failed]])
                created += 1
            elif any(str(item.get("probe_type") or "").upper() in {"DNS", "DNS_RESOLVE"} and str(item.get("error_type") or "").lower() in {"dns", "dns_error", "resolution_failed", "dns_failed", "dns_error"} for item in failed):
                dns_failed = [item for item in failed if str(item.get("probe_type") or "").upper() in {"DNS", "DNS_RESOLVE"}]
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="dns_anomaly", title="DNS 探测异常", summary="DNS 目标解析失败，但该结论仅适用于 DNS 探测证据。", severity="major", confidence=0.84, scope={**scope, "failed_target_ids": [item["target_id"] for item in dns_failed]}, evidence=[{"source_type": "probe_result", "source_id": item.get("id"), "metric": "dns", "details": item} for item in dns_failed])
                created += 1
            elif failed and successful:
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="single_target_anomaly", title="单目标探测异常", summary="仅部分探测目标失败，暂不归因于出口链路。", severity="warning", confidence=0.88, scope={**scope, "failed_target_ids": [item["target_id"] for item in failed]}, evidence=[{"source_type": "probe_result", "source_id": item.get("id"), "metric": "success", "details": item} for item in failed])
                created += 1
            elif failed and not successful and bindings:
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="egress_probe_failure", title="出口探测整体失败", summary="所有已绑定目标在同一窗口失败，结合链路状态继续判断设备、接口或路径故障。", severity="major", confidence=0.75, scope=scope, evidence=[{"source_type": "probe_result", "source_id": item.get("id"), "metric": "success", "details": item} for item in failed])
                created += 1
            util = max(float(current.get("download_util_pct") or 0), float(current.get("upload_util_pct") or 0))
            discard = sum(float(latest_sample.get(key) or 0) for key in ("in_discard_delta", "out_discard_delta"))
            high_latency = [item for item in successful if item.get("latency_ms") is not None and float(item.get("latency_ms") or 0) > 200]
            latency_consistent = len(high_latency) >= max(1, math.ceil(len(successful) / 2)) if successful else False
            if util >= 85 and (discard > 0 or latency_consistent):
                _open_or_update_correlation(conn, group=f"link:{link['id']}", code="egress_congestion", title="出口链路拥塞候选", summary="高利用率同时伴随丢弃或多个探测目标时延异常，标记为拥塞候选。", severity="major", confidence=0.8, scope={**scope, "utilization_pct": util, "discard_delta": discard, "high_latency_target_ids": [item.get("target_id") for item in high_latency]}, evidence=[{"source_type": "wan_current_status", "source_id": link["id"], "metric": "utilization_pct", "metric_value": util, "details": {**current, "latest_sample": latest_sample}}, *[{"source_type": "probe_result", "source_id": item.get("id"), "metric": "latency_ms", "metric_value": item.get("latency_ms"), "details": item} for item in high_latency]])
                created += 1
            current_dt = _parse(current.get("sampled_at")) or datetime.now(timezone.utc)
            baseline = conn.execute("SELECT * FROM wan_baselines WHERE link_id = ? AND weekday = ? AND hour = ? AND direction = 'download' AND window_days = 30", (link["id"], current_dt.weekday(), current_dt.hour)).fetchone()
            if baseline and current.get("download_bps") is not None:
                current_bps = float(current.get("download_bps") or 0)
                baseline_p95 = float(baseline["p95_bps"] or 0)
                baseline_median = float(baseline["median_bps"] or 0)
                if baseline_p95 > 0 and current_bps > baseline_p95 * 1.3:
                    _open_or_update_correlation(conn, group=f"link:{link['id']}", code="traffic_spike", title="流量突增", summary="当前流量超过同星期/小时历史 P95，需结合业务变更判断。", severity="warning", confidence=0.72, scope={**scope, "current_bps": current_bps, "baseline_p95_bps": baseline_p95}, evidence=[{"source_type": "wan_current_status", "source_id": link["id"], "metric": "download_bps", "metric_value": current_bps, "details": {"baseline_p95_bps": baseline_p95}}])
                    created += 1
                elif baseline_median > 0 and current_bps < baseline_median * 0.3:
                    _open_or_update_correlation(conn, group=f"link:{link['id']}", code="traffic_drop", title="流量突降候选", summary="当前流量显著低于同星期/小时历史中位数，已排除明显采集失败后再处理。", severity="warning", confidence=0.68, scope={**scope, "current_bps": current_bps, "baseline_median_bps": baseline_median}, evidence=[{"source_type": "wan_current_status", "source_id": link["id"], "metric": "download_bps", "metric_value": current_bps, "details": {"baseline_median_bps": baseline_median}}])
                    created += 1
        groups = [dict(row) for row in conn.execute("SELECT * FROM wan_link_groups WHERE enabled = TRUE").fetchall()]
        for group in groups:
            members = [dict(row) for row in conn.execute("SELECT m.*, c.health_status, c.oper_status, c.sampled_at FROM wan_link_group_members m JOIN wan_link_current_status c ON c.link_id = m.link_id WHERE m.group_id = ?", (group["id"],)).fetchall()]
            primary = [item for item in members if item.get("role") == "primary"]
            backups = [item for item in members if item.get("role") == "backup"]
            if primary and backups and all(item.get("health_status") in {"unavailable", "critical", "unknown"} for item in primary) and any(item.get("health_status") == "healthy" for item in backups):
                _open_or_update_correlation(conn, group=f"group:{group['id']}", code="primary_backup_failover", title="主备链路切换候选", summary="主链路不可用且备用链路健康，结合流量和探测证据确认切换。", severity="major", confidence=0.78, scope={"group_id": group["id"], "primary_ids": [item["link_id"] for item in primary], "backup_ids": [item["link_id"] for item in backups]}, evidence=[{"source_type": "wan_current_status", "source_id": item["link_id"], "metric": "health_status", "details": item} for item in members])
                created += 1
        now = _now()
        # Every enabled link and link group is evaluated in this run.  An active
        # event not refreshed during the run therefore has a current recovery
        # fact and can be closed immediately; the older cutoff remains useful
        # for events created by a failed/interrupted previous run.
        conn.execute("UPDATE wan_correlation_events SET status = 'resolved', resolved_at = ?, updated_at = ? WHERE status IN ('open', 'acknowledged') AND last_seen_at < ?", (now, now, run_started))
        conn.commit()
        return {"links": len(links), "evaluated": created, "rule_version": RULE_VERSION}
    finally:
        conn.close()


def calculate_wan_baselines(window_days: int = 30) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(window_days, 90)))).isoformat()
        rows = [dict(row) for row in conn.execute("SELECT link_id, bucket_start AS sampled_at, avg_download_bps AS download_bps, avg_upload_bps AS upload_bps, avg_download_util_pct AS download_util_pct, avg_upload_util_pct AS upload_util_pct FROM wan_link_samples_1h WHERE bucket_start >= ? AND coverage_pct >= 80", (cutoff,)).fetchall()]
        if not rows:
            rows = [dict(row) for row in conn.execute(f"SELECT link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct FROM {_sample_table()} WHERE sampled_at >= ? AND collection_status = 'success'", (cutoff,)).fetchall()]
        grouped: dict[tuple[str, str, int, int], list[float]] = {}
        util_grouped: dict[tuple[str, str, int, int], list[float]] = {}
        for row in rows:
            dt = _parse(row.get("sampled_at"))
            if not dt:
                continue
            for direction in ("download", "upload"):
                value = row.get(f"{direction}_bps")
                if value is not None:
                    grouped.setdefault((str(row["link_id"]), direction, dt.weekday(), dt.hour), []).append(float(value))
                util_value = row.get(f"{direction}_util_pct")
                if util_value is not None:
                    util_grouped.setdefault((str(row["link_id"]), direction, dt.weekday(), dt.hour), []).append(float(util_value))
        now = _now()
        for (link_id, direction, weekday, hour), values in grouped.items():
            median = statistics.median(values)
            p95 = sorted(values)[min(len(values) - 1, math.ceil(len(values) * 0.95) - 1)]
            stddev = statistics.pstdev(values) if len(values) > 1 else 0
            util_values = util_grouped.get((link_id, direction, weekday, hour), [])
            median_util = statistics.median(util_values) if util_values else None
            p95_util = sorted(util_values)[min(len(util_values) - 1, math.ceil(len(util_values) * 0.95) - 1)] if util_values else None
            conn.execute("""INSERT INTO wan_baselines (id, link_id, direction, weekday, hour, sample_count, median_bps, p95_bps, stddev_bps, median_util_pct, p95_util_pct, window_days, status, calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?) ON CONFLICT(link_id, direction, weekday, hour, window_days) DO UPDATE SET sample_count=excluded.sample_count, median_bps=excluded.median_bps, p95_bps=excluded.p95_bps, stddev_bps=excluded.stddev_bps, median_util_pct=excluded.median_util_pct, p95_util_pct=excluded.p95_util_pct, status='ready', calculated_at=excluded.calculated_at""", (f"wan-baseline-{uuid.uuid4().hex}", link_id, direction, weekday, hour, len(values), round(median), round(p95), round(stddev, 2), round(median_util, 3) if median_util is not None else None, round(p95_util, 3) if p95_util is not None else None, window_days, now))
        conn.commit()
        return {"window_days": window_days, "groups": len(grouped), "samples": len(rows)}
    finally:
        conn.close()


def build_capacity_recommendations() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        end = datetime.now(timezone.utc)
        links = [dict(row) for row in conn.execute("SELECT * FROM wan_links WHERE enabled = TRUE").fetchall()]
        created = 0
        for window_days in (7, 30, 90):
            start = end - timedelta(days=window_days)
            for link in links:
                rows = [dict(row) for row in conn.execute("SELECT * FROM wan_link_samples_1h WHERE link_id = ? AND bucket_start >= ? AND bucket_start < ? AND coverage_pct >= 80", (link["id"], start.isoformat(), end.isoformat())).fetchall()]
                p95_values = [max(float(row.get("p95_download_util_pct") or 0), float(row.get("p95_upload_util_pct") or 0)) for row in rows]
                high70 = sum(1 for value in p95_values if value >= 70)
                high85 = sum(1 for value in p95_values if value >= 85)
                high95 = sum(1 for value in p95_values if value >= 95)
                coverage = min((float(row.get("coverage_pct") or 0) for row in rows), default=0)
                if len(rows) < max(24, window_days * 24 * 0.25) or coverage < 80:
                    status, recommendation, confidence = "observing", "样本不足或采集成功率不足，继续观察", 0.2
                elif high95 >= max(3, window_days // 10) and high85 >= max(6, window_days // 2):
                    status, recommendation, confidence = "review", "建议评估扩容或流量分流", min(0.95, 0.55 + high95 / 100)
                elif high85 >= max(6, window_days // 3):
                    status, recommendation, confidence = "review", "建议评估带宽使用优化", 0.65
                elif high70:
                    status, recommendation, confidence = "observing", "已达到关注阈值，建议持续观察", 0.55
                else:
                    status, recommendation, confidence = "observing", "当前证据不足以提出扩容建议", 0.6
                evidence = {"window_days": window_days, "rollup_hours": len(rows), "p95_utilization_pct": round(max(p95_values), 3) if p95_values else None, "high70_hours": high70, "high85_hours": high85, "high95_hours": high95, "coverage_min_pct": coverage, "error_total": sum(int(row.get("in_error_total") or 0) + int(row.get("out_error_total") or 0) for row in rows), "discard_total": sum(int(row.get("in_discard_total") or 0) + int(row.get("out_discard_total") or 0) for row in rows)}
                now = _now()
                conn.execute("DELETE FROM wan_capacity_recommendations WHERE link_id = ? AND period_start = ? AND period_end = ?", (link["id"], start.isoformat(), end.isoformat()))
                conn.execute("INSERT INTO wan_capacity_recommendations (id, link_id, status, recommendation, confidence, evidence_json, period_start, period_end, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (f"wan-capacity-{uuid.uuid4().hex}", link["id"], status, recommendation, confidence, json.dumps(evidence, ensure_ascii=False), start.isoformat(), end.isoformat(), now, now))
                created += 1
        conn.commit()
        return {"links": len(links), "windows": 3, "recommendations": created}
    finally:
        conn.close()


def list_wan_correlation_events(*, page: int = 1, page_size: int = 20, status: str = "", code: str = "", severity: str = "", site_id: str = "", provider: str = "", keyword: str = "", start_at: str = "", end_at: str = "") -> dict[str, Any]:
    conn = get_db_connection()
    try:
        clauses, params = [], []
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        if code:
            clauses.append("e.root_cause_code = ?")
            params.append(code)
        if severity:
            clauses.append("e.severity = ?")
            params.append(severity)
        if site_id:
            clauses.append("l.site_id = ?")
            params.append(site_id)
        if provider:
            clauses.append("l.provider = ?")
            params.append(provider)
        if start_at:
            clauses.append("e.starts_at >= ?")
            params.append(start_at)
        if end_at:
            clauses.append("e.starts_at < ?")
            params.append(end_at)
        if keyword:
            clauses.append("(LOWER(e.title) LIKE LOWER(?) OR LOWER(e.summary) LIKE LOWER(?) OR LOWER(e.root_cause_code) LIKE LOWER(?) OR LOWER(COALESCE(l.link_name, '')) LIKE LOWER(?))")
            token = f"%{keyword}%"
            params.extend([token, token, token, token])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        join = "LEFT JOIN wan_links l ON l.id = CASE WHEN e.correlation_group LIKE 'link:%' THEN SUBSTR(e.correlation_group, 6) ELSE '' END"
        total = int(conn.execute(f"SELECT COUNT(*) FROM wan_correlation_events e {join} {where}", tuple(params)).fetchone()[0])
        rows = conn.execute(f"SELECT e.*, l.link_name, l.site_name, l.site_id, l.provider FROM wan_correlation_events e {join} {where} ORDER BY e.starts_at DESC LIMIT ? OFFSET ?", tuple(params + [page_size, (page - 1) * page_size])).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}
    finally:
        conn.close()


def get_wan_correlation_event(event_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM wan_correlation_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["scope"] = _json_object(item.pop("scope_json", "{}"))
        evidence = []
        for evidence_row in conn.execute("SELECT * FROM wan_correlation_evidence WHERE event_id = ? ORDER BY observed_at ASC", (event_id,)).fetchall():
            evidence_item = dict(evidence_row)
            evidence_item["details"] = _json_object(evidence_item.pop("details_json", "{}"))
            evidence.append(evidence_item)
        item["evidence"] = evidence
        return item
    finally:
        conn.close()


def list_wan_capacity_recommendations(link_id: str = "") -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        if link_id:
            rows = conn.execute("SELECT * FROM wan_capacity_recommendations WHERE link_id = ? ORDER BY period_end DESC", (link_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM wan_capacity_recommendations ORDER BY period_end DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            except (TypeError, ValueError):
                item["evidence"] = {}
            result.append(item)
        return result
    finally:
        conn.close()


def update_wan_capacity_recommendation(recommendation_id: str, status: str, actor: dict[str, Any], note: str = "") -> dict[str, Any] | None:
    if status not in {"observing", "review", "handled", "not_applicable"}:
        raise ValueError("Unsupported capacity recommendation status")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM wan_capacity_recommendations WHERE id = ?", (recommendation_id,)).fetchone()
        if not row:
            return None
        evidence = _json_object(dict(row).get("evidence_json"))
        if note:
            evidence["review_note"] = note
        now = _now()
        conn.execute("UPDATE wan_capacity_recommendations SET status = ?, evidence_json = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ? WHERE id = ?", (status, json.dumps(evidence, ensure_ascii=False), str(actor.get("username") or actor.get("id") or ""), now, now, recommendation_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM wan_capacity_recommendations WHERE id = ?", (recommendation_id,)).fetchone()
        item = dict(updated) if updated else None
        if item:
            item["evidence"] = _json_object(item.pop("evidence_json", "{}"))
        return item
    finally:
        conn.close()


def get_wan_cockpit() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        summary = conn.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN health_status = 'healthy' THEN 1 ELSE 0 END) AS healthy, SUM(CASE WHEN health_status IN ('critical', 'unavailable') THEN 1 ELSE 0 END) AS risky, SUM(active_alert_count) AS active_alerts FROM wan_link_current_status").fetchone()
        correlations = conn.execute("SELECT root_cause_code, COUNT(*) AS count FROM wan_correlation_events WHERE status IN ('open', 'acknowledged') GROUP BY root_cause_code ORDER BY count DESC").fetchall()
        recommendations = conn.execute("SELECT status, COUNT(*) AS count FROM wan_capacity_recommendations GROUP BY status").fetchall()
        active = [dict(row) for row in conn.execute("SELECT id, correlation_group, root_cause_code, severity, status, confidence, title, summary, starts_at, last_seen_at, scope_json FROM wan_correlation_events WHERE status IN ('open', 'acknowledged') ORDER BY starts_at DESC LIMIT 20").fetchall()]
        for item in active:
            try:
                item["scope"] = json.loads(item.pop("scope_json") or "{}")
            except (TypeError, ValueError):
                item["scope"] = {}
        latest_capacity = [dict(row) for row in conn.execute("SELECT r.* FROM wan_capacity_recommendations r JOIN (SELECT link_id, MAX(period_end) AS latest FROM wan_capacity_recommendations GROUP BY link_id) x ON x.link_id = r.link_id AND x.latest = r.period_end ORDER BY r.updated_at DESC LIMIT 30").fetchall()]
        for item in latest_capacity:
            try:
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            except (TypeError, ValueError):
                item["evidence"] = {}
        return {"summary": dict(summary or {}), "correlations": [dict(row) for row in correlations], "active_events": active, "recommendations": [dict(row) for row in recommendations], "latest_capacity": latest_capacity}
    finally:
        conn.close()
