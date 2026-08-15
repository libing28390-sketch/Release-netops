"""Deterministic alert lifecycle, health, correlation and storm controls."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


ALERT_STATES = {"OK", "PENDING", "ACTIVE", "RECOVERING", "RESOLVED", "FLAPPING"}
HEALTH_STATES = {"UP", "DEGRADED", "UNREACHABLE", "UNKNOWN"}


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)


@dataclass
class AlertState:
    state: str = "OK"
    pending_since: datetime | None = None
    recovery_since: datetime | None = None
    breach_count: int = 0
    recovery_count: int = 0
    flap_count: int = 0
    transitions: list[tuple[str, str, datetime]] = field(default_factory=list)


@dataclass(frozen=True)
class Transition:
    state: str
    emit: bool
    event: str
    reason: str


def transition_state(
    current: AlertState,
    *,
    breached: bool,
    now: datetime | None = None,
    for_seconds: int = 0,
    recovery_threshold: int = 1,
    recovery_seconds: int = 0,
) -> Transition:
    """Apply FOR/PENDING and recovery hysteresis without deleting raw signals."""
    now = _now(now)
    for_seconds = max(0, int(for_seconds or 0))
    recovery_threshold = max(1, int(recovery_threshold or 1))
    recovery_seconds = max(0, int(recovery_seconds or 0))
    previous = current.state

    if breached:
        current.breach_count += 1
        current.recovery_count = 0
        current.recovery_since = None
        if current.state in {"OK", "RESOLVED", "RECOVERING"}:
            current.pending_since = current.pending_since or now
            elapsed = (now - current.pending_since).total_seconds()
            if for_seconds and elapsed < for_seconds:
                current.state = "PENDING"
                return Transition("PENDING", False, "pending_started" if previous != "PENDING" else "pending_observed", "for_duration_not_met")
            current.state = "ACTIVE"
            current.pending_since = None
            current.transitions.append((previous, "ACTIVE", now))
            return Transition("ACTIVE", True, "alert_opened", "threshold_and_for_duration_met")
        if current.state == "PENDING":
            elapsed = (now - (current.pending_since or now)).total_seconds()
            if for_seconds and elapsed < for_seconds:
                return Transition("PENDING", False, "pending_observed", "for_duration_not_met")
            current.state = "ACTIVE"
            current.pending_since = None
            current.transitions.append((previous, "ACTIVE", now))
            return Transition("ACTIVE", True, "alert_opened", "for_duration_met")
        current.state = "ACTIVE"
        return Transition("ACTIVE", False, "alert_repeated", "still_breached")

    current.recovery_count += 1
    current.breach_count = 0
    if current.state in {"ACTIVE", "FLAPPING", "RECOVERING"}:
        current.recovery_since = current.recovery_since or now
        elapsed = (now - current.recovery_since).total_seconds()
        if current.recovery_count < recovery_threshold or (recovery_seconds and elapsed < recovery_seconds):
            current.state = "RECOVERING"
            return Transition("RECOVERING", False, "recovery_observed", "recovery_hysteresis_not_met")
        current.state = "RESOLVED"
        current.recovery_since = None
        current.transitions.append((previous, "RESOLVED", now))
        return Transition("RESOLVED", True, "alert_resolved", "recovery_threshold_and_duration_met")
    current.pending_since = None
    current.recovery_since = None
    current.state = "OK"
    return Transition("OK", False, "healthy_observed", "no_active_alert")


def detect_flapping(
    transitions: Iterable[datetime],
    *,
    now: datetime | None = None,
    window_seconds: int = 600,
    threshold: int = 4,
) -> bool:
    now = _now(now)
    cutoff = now - timedelta(seconds=max(1, int(window_seconds)))
    return sum(1 for item in transitions if item >= cutoff) >= max(2, int(threshold))


def compute_health(*, icmp: bool | None, snmp: bool | None, ssh: bool | None) -> dict[str, Any]:
    values = [value for value in (icmp, snmp, ssh) if value is not None]
    if not values:
        return {"state": "UNKNOWN", "icmp": icmp, "snmp": snmp, "ssh": ssh, "evidence": []}
    if all(values):
        state = "UP"
    elif any(values):
        state = "DEGRADED"
    else:
        state = "UNREACHABLE"
    return {
        "state": state,
        "icmp": icmp,
        "snmp": snmp,
        "ssh": ssh,
        "evidence": [name for name, value in (("icmp", icmp), ("snmp", snmp), ("ssh", ssh)) if value is not None],
    }


def check_no_data(last_sample_at: datetime | None, *, now: datetime | None = None, threshold_seconds: int = 300) -> bool:
    if last_sample_at is None:
        return True
    return (_now(now) - last_sample_at).total_seconds() > max(1, int(threshold_seconds))


def suppress_dependency_alerts(alerts: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark downstream alerts suppressed while preserving each raw alert."""
    upstream_by_target: defaultdict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.get("relation_type") in {"PHYSICAL", "HIERARCHICAL", "LOGICAL"} and edge.get("status", "active") == "active":
            upstream_by_target[str(edge.get("target_node_id"))].add(str(edge.get("source_node_id")))
    by_device = {str(alert.get("device_id")): alert for alert in alerts if alert.get("device_id")}
    result: list[dict[str, Any]] = []
    for alert in alerts:
        item = dict(alert)
        causes = [by_device[source] for source in upstream_by_target.get(str(alert.get("device_id")), set()) if by_device.get(source)]
        if causes:
            root = min(causes, key=lambda candidate: str(candidate.get("created_at") or ""))
            item["is_suppressed"] = True
            item["suppression_type"] = "dependency"
            item["suppressed_by_alert_id"] = root.get("id")
            item["root_alert_id"] = root.get("id")
            item["suppression_evidence"] = ["topology_dependency", root.get("id")]
        else:
            item["is_suppressed"] = bool(item.get("is_suppressed", False))
        result.append(item)
    return result


def correlate_alerts(alerts: list[dict[str, Any]], *, time_window_seconds: int = 300) -> list[dict[str, Any]]:
    """Return deterministic correlation links with explainable evidence."""
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        key = str(alert.get("correlation_key") or alert.get("device_id") or alert.get("site_id") or "unknown")
        groups[key].append(alert)
    result: list[dict[str, Any]] = []
    for key, items in groups.items():
        items.sort(key=lambda item: str(item.get("created_at") or ""))
        root = items[0] if items else None
        for item in items:
            if not root or item.get("id") == root.get("id"):
                continue
            same_type = item.get("type") == root.get("type")
            confidence = 0.9 if same_type else 0.7
            result.append({
                "alert_id": item.get("id"),
                "root_alert_id": root.get("id"),
                "correlation_type": "same_scope" if same_type else "shared_scope",
                "confidence": confidence,
                "evidence": ["same_correlation_key", key],
            })
    return result


def detect_storm(alerts: list[dict[str, Any]], *, window_seconds: int = 300, count_threshold: int = 20) -> dict[str, Any]:
    counts = Counter(str(item.get("site_id") or "unknown") for item in alerts)
    types = Counter(str(item.get("type") or item.get("title") or "unknown") for item in alerts)
    is_storm = len(alerts) >= max(1, count_threshold)
    return {
        "is_storm": is_storm,
        "alert_count": len(alerts),
        "site_count": len(counts),
        "type_count": len(types),
        "top_sites": counts.most_common(10),
        "top_types": types.most_common(10),
        "window_seconds": window_seconds,
        "raw_alert_ids": [item.get("id") for item in alerts],
    }


def calculate_impact(alert: dict[str, Any], *, graph_nodes: list[dict[str, Any]], graph_edges: list[dict[str, Any]]) -> dict[str, Any]:
    device_id = str(alert.get("device_id") or "")
    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    for edge in graph_edges:
        if edge.get("status", "active") != "active":
            continue
        source = str(edge.get("source_node_id"))
        target = str(edge.get("target_node_id"))
        adjacency[source].add(target)
        adjacency[target].add(source)
    impacted: set[str] = set()
    frontier = [device_id] if device_id else []
    for _ in range(3):
        next_frontier = []
        for current in frontier:
            for neighbor in adjacency.get(current, set()):
                if neighbor not in impacted and neighbor != device_id:
                    impacted.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
    critical = sum(1 for node in graph_nodes if str(node.get("id")) in impacted and str(node.get("function") or "").lower() in {"service", "gateway", "database"})
    score = min(100.0, 20.0 + len(impacted) * 5.0 + critical * 15.0)
    return {"impact_score": round(score, 2), "impacted_node_ids": sorted(impacted), "critical_impacted_count": critical}


def rank_rca_candidates(alerts: list[dict[str, Any]], correlations: list[dict[str, Any]], *, topology_edges: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    roots = Counter(str(item.get("root_alert_id") or item.get("alert_id")) for item in correlations)
    candidates = []
    for alert in alerts:
        alert_id = str(alert.get("id") or "")
        evidence = ["earliest_alert"]
        score = 0.5
        if roots.get(alert_id):
            score += min(0.4, roots[alert_id] * 0.05)
            evidence.append("correlated_dependents")
        if str(alert.get("source") or "").lower() in {"device_health", "network_monitor"}:
            score += 0.1
            evidence.append("infrastructure_signal")
        candidates.append({"alert_id": alert_id, "confidence": round(min(score, 0.99), 3), "evidence": evidence})
    return sorted(candidates, key=lambda item: (-item["confidence"], item["alert_id"]))


def impact_severity_suggestion(*, severity: str, impact_score: float, critical_count: int = 0) -> str:
    current = str(severity or "minor").lower()
    if critical_count > 0 or impact_score >= 80:
        return "critical"
    if impact_score >= 50 and current in {"info", "minor", "warning"}:
        return "major"
    return current


def rule_checksum(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def silence_matches(alert: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Match a short-lived notification silence without changing alert state."""
    def values(key: str) -> set[str]:
        raw = scope.get(key) or []
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        return {str(item).strip() for item in raw if str(item).strip()}

    device_ids = values("device_ids")
    site_ids = values("site_ids")
    alert_types = values("alert_types") | values("types")
    if device_ids and str(alert.get("device_id") or "") not in device_ids:
        return False
    if site_ids and str(alert.get("site_id") or alert.get("site") or "") not in site_ids:
        return False
    if alert_types and str(alert.get("type") or alert.get("source") or alert.get("dedupe_key") or "") not in alert_types:
        return False
    return bool(device_ids or site_ids or alert_types) or not scope


def find_active_silence_for_alert(alert: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """Return an active silence if present; failures fail open for alerting."""
    now_iso = _now(now).isoformat()
    tenant_id = str(alert.get("tenant_id") or "tenant-default")
    try:
        from database import get_db_connection
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, tenant_id, scope_json, reason, starts_at, ends_at, created_by FROM alert_silences WHERE status = 'active' AND (tenant_id = ? OR tenant_id = 'tenant-default') AND starts_at <= ? AND ends_at >= ? ORDER BY starts_at DESC",
                (tenant_id, now_iso, now_iso),
            ).fetchall()
            for row in rows:
                try:
                    scope = json.loads(row[2] or "{}")
                except (TypeError, ValueError):
                    scope = {}
                if silence_matches(alert, scope):
                    return {"id": row[0], "tenant_id": row[1], "scope": scope, "reason": row[3], "starts_at": row[4], "ends_at": row[5], "created_by": row[6]}
    except Exception:
        return None
    return None
