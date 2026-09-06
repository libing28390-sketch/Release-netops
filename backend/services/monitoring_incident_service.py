"""Incident aggregation for the NOC monitoring center.

Alert events remain the immutable-ish operational timeline.  This service
maintains a small incident projection that groups related active alerts,
supports acknowledgement/assignment, and exposes the related alert history
without changing the existing alert APIs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


INCIDENT_OPEN_STATUSES = {"open", "acknowledged", "investigating"}
SEVERITY_RANK = {"critical": 0, "major": 1, "warning": 2, "minor": 3, "info": 4}
_REACHABILITY_MARKERS = (
    "offline",
    "unreachable",
    "snmp_unreachable",
    "ssh_unreachable",
    "ping_unreachable",
    "probe_failed",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _append_timeline(
    conn,
    incident_id_value: str,
    event_type: str,
    actor: str,
    message: str,
    details: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO monitoring_incident_timeline
            (id, incident_id, event_type, actor, message, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            incident_id_value,
            event_type,
            actor or "",
            message,
            json.dumps(details or {}, ensure_ascii=False),
            created_at or utc_now_iso(),
        ),
    )


def append_incident_timeline(
    conn,
    incident_id_value: str,
    event_type: str,
    actor: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a durable operator/audit event to an incident timeline.

    The internal helper is used by incident state transitions.  This public
    wrapper lets diagnostics, work-order handoff, and safe Playbook
    recommendations use the same timeline without duplicating SQL.
    """
    _append_timeline(conn, incident_id_value, event_type, actor, message, details)


def _severity(alert: dict[str, Any]) -> str:
    value = str(alert.get("severity") or "warning").strip().lower()
    return value if value in SEVERITY_RANK else "warning"


def incident_group_key(alert: dict[str, Any]) -> str:
    """Return a deterministic grouping key for one active alert.

    Connectivity failures from the same device are intentionally grouped so
    Ping/SNMP/SSH failures do not create three operator-facing incidents.  All
    other alert types retain their dedupe key to avoid merging unrelated
    capacity or interface problems.
    """
    device_id = str(alert.get("device_id") or "").strip()
    text = " ".join(
        str(alert.get(field) or "").lower()
        for field in ("dedupe_key", "source", "title", "message")
    )
    if device_id and any(marker in text for marker in _REACHABILITY_MARKERS):
        return f"device:{device_id}:reachability"
    return f"alert:{str(alert.get('dedupe_key') or alert.get('id') or '').strip()}"


def incident_id(group_key: str, first_seen_at: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{group_key}|{first_seen_at}".encode("utf-8")).hexdigest()[:16].upper()
    day = str(first_seen_at or "")[:10].replace("-", "") or "UNKNOWN"
    incident_key = f"INC-{day}-{digest}"
    return f"incident-{digest.lower()}", incident_key


def _active_alerts(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.id, a.dedupe_key, a.source, a.severity, a.title, a.message,
               a.device_id, a.interface_name, a.created_at, a.resolved_at,
               a.workflow_status, a.assignee, a.ack_by, a.ack_at, a.note,
               a.updated_at, d.hostname, d.ip_address,
               COALESCE(NULLIF(s.site_name, ''),
                        CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END,
                        '') AS site
        FROM alert_events a
        LEFT JOIN devices d ON d.id = a.device_id
        LEFT JOIN sites s ON s.id = d.site_id
        WHERE a.resolved_at IS NULL
          AND COALESCE(a.workflow_status, 'open') != 'suppressed'
        ORDER BY a.created_at ASC, a.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def sync_incidents(conn) -> list[dict[str, Any]]:
    """Reconcile active alert events into the incident projection.

    The operation is idempotent and runs in the caller's transaction.  A new
    incident identity includes the group's first-seen timestamp, so a group
    that was resolved and later re-opened gets a new incident rather than
    silently reopening the historical one.
    """
    now = utc_now_iso()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in _active_alerts(conn):
        groups[incident_group_key(alert)].append(alert)

    active_ids: list[str] = []
    for group_key, alerts in groups.items():
        first_seen = str(alerts[0].get("created_at") or now)
        last_seen = str(alerts[-1].get("created_at") or first_seen)
        root_alert = min(
            alerts,
            key=lambda item: (SEVERITY_RANK.get(_severity(item), 99), str(item.get("created_at") or ""), str(item.get("id") or "")),
        )
        primary = alerts[0]
        severity = min((_severity(item) for item in alerts), key=lambda value: SEVERITY_RANK.get(value, 99))
        incident_id_value, incident_key = incident_id(group_key, first_seen)
        related_count = len(alerts)
        device_ids = {str(item.get("device_id") or "") for item in alerts if item.get("device_id")}
        title = str(root_alert.get("title") or "Active monitoring incident")
        if related_count > 1:
            title = f"{title} (+{related_count - 1} related alerts)"
        summary = str(root_alert.get("message") or title)
        site = str(primary.get("site") or "")
        existed = conn.execute(
            "SELECT 1 FROM monitoring_incidents WHERE id = ?",
            (incident_id_value,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO monitoring_incidents (
                id, incident_key, title, summary, severity, status, source,
                root_cause_alert_id, primary_device_id, site, first_seen_at,
                last_seen_at, impact_device_count, impact_alert_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'open', 'alert_events', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (incident_key) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                severity = excluded.severity,
                root_cause_alert_id = excluded.root_cause_alert_id,
                primary_device_id = excluded.primary_device_id,
                site = excluded.site,
                last_seen_at = excluded.last_seen_at,
                impact_device_count = excluded.impact_device_count,
                impact_alert_count = excluded.impact_alert_count,
                status = CASE
                    WHEN monitoring_incidents.status IN ('acknowledged', 'investigating') THEN monitoring_incidents.status
                    ELSE 'open'
                END,
                resolved_at = NULL,
                updated_at = excluded.updated_at
            """,
            (
                incident_id_value,
                incident_key,
                title,
                summary,
                severity,
                str(root_alert.get("id") or ""),
                str(primary.get("device_id") or "") or None,
                site,
                first_seen,
                last_seen,
                len(device_ids),
                related_count,
                first_seen,
                now,
            ),
        )
        if not existed:
            _append_timeline(
                conn,
                incident_id_value,
                "incident_opened",
                "system",
                title,
                {"root_alert_id": root_alert.get("id"), "alert_count": related_count, "device_count": len(device_ids)},
                first_seen,
            )
        active_ids.append(incident_id_value)
        for alert in alerts:
            conn.execute(
                """
                INSERT INTO monitoring_incident_alerts (incident_id, alert_id, linked_at, is_root)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (incident_id, alert_id) DO UPDATE SET
                    is_root = excluded.is_root
                """,
                (incident_id_value, str(alert.get("id") or ""), now, 1 if alert.get("id") == root_alert.get("id") else 0),
            )

    if active_ids:
        placeholders = ", ".join("?" for _ in active_ids)
        conn.execute(
            f"""
            UPDATE monitoring_incidents
            SET status = 'resolved', resolved_at = COALESCE(resolved_at, ?), updated_at = ?
            WHERE status IN ('open', 'acknowledged', 'investigating')
              AND id NOT IN ({placeholders})
            """,
            (now, now, *active_ids),
        )
    else:
        conn.execute(
            """
            UPDATE monitoring_incidents
            SET status = 'resolved', resolved_at = COALESCE(resolved_at, ?), updated_at = ?
            WHERE status IN ('open', 'acknowledged', 'investigating')
            """,
            (now, now),
        )
    conn.commit()
    return list_incidents(conn, status="all", sync=False)["items"]


def list_incidents(
    conn,
    *,
    status: str = "active",
    severity: str = "all",
    site: str = "all",
    device_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sync: bool = True,
) -> dict[str, Any]:
    if sync:
        sync_incidents(conn)
    clauses: list[str] = []
    params: list[Any] = []
    status_value = (status or "active").lower()
    if status_value == "active":
        clauses.append("i.status IN ('open', 'acknowledged', 'investigating')")
    elif status_value != "all":
        clauses.append("i.status = ?")
        params.append(status_value)
    if severity and severity.lower() != "all":
        clauses.append("i.severity = ?")
        params.append(severity.lower())
    if site and site.lower() != "all":
        clauses.append("COALESCE(i.site, '') = ?")
        params.append(site)
    if device_id:
        clauses.append("EXISTS (SELECT 1 FROM monitoring_incident_alerts ia2 JOIN alert_events a2 ON a2.id = ia2.alert_id WHERE ia2.incident_id = i.id AND a2.device_id = ?)")
        params.append(device_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) AS c FROM monitoring_incidents i {where_sql}", tuple(params)).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT i.*, d.hostname, d.ip_address,
               COUNT(ia.alert_id) AS related_alert_count
        FROM monitoring_incidents i
        LEFT JOIN devices d ON d.id = i.primary_device_id
        LEFT JOIN monitoring_incident_alerts ia ON ia.incident_id = i.id
        {where_sql}
        GROUP BY i.id, d.hostname, d.ip_address
        ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'investigating' THEN 1 WHEN 'acknowledged' THEN 2 ELSE 3 END,
                 CASE i.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                 i.last_seen_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, offset]),
    ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def get_incident(conn, incident_id_value: str, *, sync: bool = True) -> dict[str, Any] | None:
    if sync:
        sync_incidents(conn)
    row = conn.execute(
        """
        SELECT i.*, d.hostname, d.ip_address
        FROM monitoring_incidents i
        LEFT JOIN devices d ON d.id = i.primary_device_id
        WHERE i.id = ?
        """,
        (incident_id_value,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    alert_rows = conn.execute(
        """
        SELECT a.*, ia.is_root, d.hostname, d.ip_address,
               COALESCE(NULLIF(s.site_name, ''),
                        CASE WHEN SUBSTR(COALESCE(d.site, ''), 1, 5) = 'site-' THEN '' ELSE COALESCE(d.site, '') END,
                        '') AS site
        FROM monitoring_incident_alerts ia
        JOIN alert_events a ON a.id = ia.alert_id
        LEFT JOIN devices d ON d.id = a.device_id
        LEFT JOIN sites s ON s.id = d.site_id
        WHERE ia.incident_id = ?
        ORDER BY a.created_at ASC
        """,
        (incident_id_value,),
    ).fetchall()
    alerts = [dict(alert) for alert in alert_rows]
    item["alerts"] = alerts
    event_rows = conn.execute(
        """
        SELECT id, event_type, actor, message, details_json, created_at
        FROM monitoring_incident_timeline
        WHERE incident_id = ?
        ORDER BY created_at ASC
        """,
        (incident_id_value,),
    ).fetchall()
    events: list[dict[str, Any]] = []
    for event in event_rows:
        event_item = dict(event)
        try:
            event_item["details"] = json.loads(event_item.get("details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            event_item["details"] = {}
        events.append(event_item)
    alert_events = [
        {
            **alert,
            "event_type": "alert",
            "actor": "system",
            "message": alert.get("message") or alert.get("title") or "",
        }
        for alert in alerts
    ]
    item["timeline"] = sorted(events + alert_events, key=lambda event: str(event.get("created_at") or ""))
    item["impact_devices"] = [
        {"device_id": device_id, "hostname": next((str(alert.get("hostname") or "") for alert in alerts if str(alert.get("device_id") or "") == device_id), "")}
        for device_id in sorted({str(alert.get("device_id") or "") for alert in alerts if alert.get("device_id")})
    ]
    change_order_columns = _table_columns(conn, "change_orders")
    if {"incident_id", "created_at"}.issubset(change_order_columns):
        work_order_rows = conn.execute(
            "SELECT id, order_number, title, status FROM change_orders "
            "WHERE incident_id = ? ORDER BY created_at DESC",
            (incident_id_value,),
        ).fetchall()
        item["work_orders"] = [dict(work_order) for work_order in work_order_rows]
    else:
        item["work_orders"] = []
    return item


def get_incident_impact(conn, incident_id_value: str, *, sync: bool = True) -> dict[str, Any] | None:
    incident = get_incident(conn, incident_id_value, sync=sync)
    if incident is None:
        return None
    device_ids = sorted({
        str(alert.get("device_id") or "")
        for alert in incident.get("alerts", [])
        if alert.get("device_id")
    })
    nodes: list[dict[str, Any]] = []
    if device_ids:
        placeholders = ",".join("?" for _ in device_ids)
        rows = conn.execute(
            f"SELECT id, hostname, ip_address, site, site_id, role FROM devices WHERE id IN ({placeholders})",
            tuple(device_ids),
        ).fetchall()
        nodes = [dict(row) for row in rows]
    links: list[dict[str, Any]] = []
    if device_ids:
        placeholders = ",".join("?" for _ in device_ids)
        rows = conn.execute(
            f"""
            SELECT id, source_device_id, target_device_id, source_hostname,
                   target_hostname, source_port, target_port, status,
                   confidence, discovery_source
            FROM topology_links
            WHERE source_device_id IN ({placeholders})
               OR target_device_id IN ({placeholders})
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 200
            """,
            tuple([*device_ids, *device_ids]),
        ).fetchall()
        links = [dict(row) for row in rows]
        neighbor_ids = sorted({
            str(link.get("source_device_id") or "")
            for link in links
            if link.get("source_device_id") and str(link.get("source_device_id")) not in device_ids
        } | {
            str(link.get("target_device_id") or "")
            for link in links
            if link.get("target_device_id") and str(link.get("target_device_id")) not in device_ids
        })
        if neighbor_ids:
            neighbor_placeholders = ",".join("?" for _ in neighbor_ids)
            neighbor_rows = conn.execute(
                f"SELECT id, hostname, ip_address, site, site_id, role FROM devices WHERE id IN ({neighbor_placeholders})",
                tuple(neighbor_ids),
            ).fetchall()
            nodes.extend(dict(row) for row in neighbor_rows)
    affected_device_ids = set(device_ids)
    nodes = [
        {**node, "impact_scope": "affected" if str(node.get("id") or "") in affected_device_ids else "neighbor"}
        for node in nodes
    ]
    root_alert = next(
        (alert for alert in incident.get("alerts", []) if alert.get("is_root")),
        next((alert for alert in incident.get("alerts", []) if str(alert.get("id") or "") == str(incident.get("root_cause_alert_id") or "")), None),
    )
    evidence = []
    if root_alert:
        evidence.append(f"Root alert: {root_alert.get('title') or root_alert.get('message') or root_alert.get('id')}")
    if links:
        evidence.append(f"Topology evidence: {len(links)} related link(s)")
    if incident.get("source"):
        evidence.append(f"Alert source: {incident.get('source')}")
    topology_degree: dict[str, int] = defaultdict(int)
    for link in links:
        for field in ("source_device_id", "target_device_id"):
            link_device_id = str(link.get(field) or "").strip()
            if link_device_id:
                topology_degree[link_device_id] += 1
    candidate_scores: dict[str, int] = {}
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        role = str(node.get("role") or "").lower()
        role_weight = 30 if "core" in role else 20 if any(value in role for value in ("distribution", "aggregation", "汇聚")) else 10 if any(value in role for value in ("firewall", "router", "load", "出口", "路由")) else 0
        candidate_scores[node_id] = topology_degree.get(node_id, 0) * 10 + role_weight
    if root_alert and root_alert.get("device_id"):
        root_id = str(root_alert.get("device_id"))
        candidate_scores[root_id] = candidate_scores.get(root_id, 0) + 40
    root_candidate_id = max(candidate_scores, key=candidate_scores.get) if candidate_scores else None
    root_candidate = next((node for node in nodes if str(node.get("id") or "") == root_candidate_id), None)
    if root_candidate:
        evidence.append(
            f"Topology heuristic candidate: {root_candidate.get('hostname') or root_candidate_id} "
            f"({candidate_scores.get(root_candidate_id, 0)} points from alert, role, and link degree)"
        )
    site_ids = sorted({str(node.get("site_id") or "") for node in nodes if node.get("site_id")})
    site_names = sorted({str(node.get("site") or "") for node in nodes if node.get("site")})
    site_contacts: list[dict[str, Any]] = []
    business_systems: set[str] = set()
    business_units: set[str] = set()
    business_owners: set[str] = set()
    data_gaps: list[str] = []
    if site_ids:
        site_placeholders = ",".join("?" for _ in site_ids)
        site_columns = _table_columns(conn, "sites")
        if {"id", "site_name", "contact_name", "contact_phone", "contact_email"}.issubset(site_columns):
            site_rows = conn.execute(
                f"SELECT id, site_name, contact_name, contact_phone, contact_email FROM sites WHERE id IN ({site_placeholders})",
                tuple(site_ids),
            ).fetchall()
            for row in site_rows:
                item = dict(row)
                if item.get("site_name"):
                    site_names.append(str(item["site_name"]))
                if any(item.get(key) for key in ("contact_name", "contact_phone", "contact_email")):
                    site_contacts.append({
                        "site_id": item.get("id"),
                        "site_name": item.get("site_name") or item.get("id"),
                        "name": item.get("contact_name") or "",
                        "phone": item.get("contact_phone") or "",
                        "email": item.get("contact_email") or "",
                    })
        else:
            data_gaps.append("Site contact details are unavailable in the current CMDB snapshot.")
        binding_columns = _table_columns(conn, "vlan_business_bindings")
        if {"site_id", "business_system", "department", "owner", "business_level", "status"}.issubset(binding_columns):
            binding_rows = conn.execute(
                f"SELECT business_system, department, owner, business_level FROM vlan_business_bindings WHERE site_id IN ({site_placeholders}) AND COALESCE(status, 'active') = 'active'",
                tuple(site_ids),
            ).fetchall()
            for row in binding_rows:
                business_systems.add(str(row["business_system"] or "").strip())
                business_units.add(str(row["department"] or "").strip())
                business_owners.add(str(row["owner"] or "").strip())
        else:
            data_gaps.append("No VLAN business binding data is available for the affected site scope.")
    if not site_names:
        data_gaps.append("Affected devices do not have a user-defined site mapping.")
    if not business_systems:
        data_gaps.append("No active business-system binding is configured for the affected sites.")
    return {
        "incident_id": incident_id_value,
        "nodes": nodes,
        "links": links,
        "summary": {
            "affected_devices": len(device_ids),
            "incident_devices": len(device_ids),
            "topology_nodes": len(nodes),
            "related_links": len(links),
            "topology_available": bool(links),
        },
        "inference": {
            "root_cause_alert_id": incident.get("root_cause_alert_id"),
            "candidate_device_id": root_candidate_id,
            "candidate_hostname": root_candidate.get("hostname") if root_candidate else None,
            "candidate_score": candidate_scores.get(root_candidate_id) if root_candidate_id else None,
            "method": "topology_role_alert_heuristic",
            "confidence": "high" if root_alert and links and root_candidate_id else "medium" if root_alert or links else "low",
            "evidence": evidence,
            "disclaimer": "The candidate is an evidence-based topology heuristic, not a confirmed root cause; an operator must verify it.",
        },
        "business_impact": {
            "sites": sorted(set(site_names)),
            "services": sorted(value for value in business_systems if value),
            "business_units": sorted(value for value in business_units if value),
            "owners": sorted(value for value in business_owners if value),
            "contacts": site_contacts,
            "confidence": "high" if business_systems and site_contacts else "medium" if business_systems or site_contacts else "low",
            "data_gaps": data_gaps or ["Business impact is derived from current CMDB relationships and may be incomplete."],
        },
    }


def update_incident_status(conn, incident_id_value: str, status: str, actor: str) -> dict[str, Any] | None:
    status_value = status.lower().strip()
    if status_value not in {"acknowledged", "investigating", "resolved"}:
        raise ValueError("Unsupported incident status")
    row = conn.execute("SELECT * FROM monitoring_incidents WHERE id = ?", (incident_id_value,)).fetchone()
    if not row:
        return None
    now = utc_now_iso()
    if status_value == "resolved":
        conn.execute(
            "UPDATE monitoring_incidents SET status = 'resolved', resolved_at = COALESCE(resolved_at, ?), updated_at = ? WHERE id = ?",
            (now, now, incident_id_value),
        )
        _append_timeline(conn, incident_id_value, "incident_resolved", actor, "Incident resolved", {"status": status_value})
        conn.execute(
            """
            UPDATE alert_events
            SET resolved_at = COALESCE(resolved_at, ?), workflow_status = 'resolved', updated_at = ?
            WHERE id IN (SELECT alert_id FROM monitoring_incident_alerts WHERE incident_id = ?)
              AND resolved_at IS NULL
            """,
            (now, now, incident_id_value),
        )
    else:
        conn.execute(
            """
            UPDATE monitoring_incidents
            SET status = ?, acknowledged_by = COALESCE(acknowledged_by, ?),
                acknowledged_at = COALESCE(acknowledged_at, ?), updated_at = ?
            WHERE id = ?
            """,
            (status_value, actor, now, now, incident_id_value),
        )
        _append_timeline(conn, incident_id_value, f"incident_{status_value}", actor, f"Incident status changed to {status_value}", {"status": status_value})
        conn.execute(
            """
            UPDATE alert_events
            SET workflow_status = ?, ack_by = COALESCE(ack_by, ?), ack_at = COALESCE(ack_at, ?), updated_at = ?
            WHERE id IN (SELECT alert_id FROM monitoring_incident_alerts WHERE incident_id = ?)
              AND resolved_at IS NULL
            """,
            (status_value, actor, now, now, incident_id_value),
        )
    conn.commit()
    return get_incident(conn, incident_id_value, sync=False)


def assign_incident(conn, incident_id_value: str, assignee: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT id FROM monitoring_incidents WHERE id = ?", (incident_id_value,)).fetchone()
    if not row:
        return None
    now = utc_now_iso()
    conn.execute("UPDATE monitoring_incidents SET assigned_to = ?, updated_at = ? WHERE id = ?", (assignee, now, incident_id_value))
    conn.execute(
        "UPDATE alert_events SET assignee = ?, updated_at = ? WHERE id IN (SELECT alert_id FROM monitoring_incident_alerts WHERE incident_id = ?)",
        (assignee, now, incident_id_value),
    )
    _append_timeline(conn, incident_id_value, "incident_assigned", assignee, f"Incident assigned to {assignee}", {"assignee": assignee})
    conn.commit()
    return get_incident(conn, incident_id_value, sync=False)


def recommend_incident_playbooks(conn, incident_id_value: str) -> dict[str, Any] | None:
    """Return platform-bound, read-only Playbook recommendations.

    Recommendations deliberately exclude any scenario with an execute phase.
    A monitoring incident must never turn into a configuration change merely
    because an operator opened the detail drawer.  The existing Playbook
    catalog remains the source of commands and platform compatibility.
    """
    incident = get_incident(conn, incident_id_value, sync=False)
    if incident is None:
        return None

    device_id = str(incident.get("primary_device_id") or "").strip()
    device = None
    if device_id:
        row = conn.execute(
            "SELECT id, hostname, platform, vendor FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        device = dict(row) if row else None
    if not device:
        return {
            "incident_id": incident_id_value,
            "device": None,
            "items": [],
            "message": "No primary device is available for platform-bound recommendations.",
        }

    # Local import avoids making the monitoring projection depend on the
    # Playbook router during application import.
    from api.playbooks.scenarios import _normalize_playbook_platform, resolve_platform_phases, _all_scenarios

    platform = _normalize_playbook_platform(device.get("platform"), device.get("vendor"))
    incident_text = " ".join(
        str(incident.get(field) or "")
        for field in ("title", "summary", "source")
    ).lower()
    markers = {
        "reachability": ("offline", "unreachable", "snmp", "ssh", "ping", "probe", "connect", "采集", "连通"),
        "hardware": ("fan", "power", "temperature", "hardware", "风扇", "电源", "温度"),
        "routing": ("bgp", "ospf", "route", "routing", "路由", "邻居"),
        "interface": ("interface", "port", "link", "flap", "error", "接口", "链路"),
    }
    matched_domains = [name for name, values in markers.items() if any(value in incident_text for value in values)]

    recommendations: list[dict[str, Any]] = []
    for scenario in _all_scenarios():
        scenario_id = str(scenario.get("id") or "").strip()
        if not scenario_id:
            continue
        try:
            phases, resolved_platform = resolve_platform_phases(
                scenario.get("platform_phases") or {},
                platform,
                device.get("vendor"),
            )
        except KeyError:
            continue
        execute_commands = phases.get("execute") or []
        if execute_commands:
            continue
        pre_check = phases.get("pre_check") or []
        if not pre_check:
            continue
        scenario_text = " ".join(
            str(scenario.get(field) or "")
            for field in ("id", "name", "description", "name_zh", "description_zh", "category")
        ).lower()
        matched_domain = next((domain for domain in matched_domains if any(marker in scenario_text for marker in markers[domain])), None)
        score = 100 if matched_domain else 10
        if str(scenario.get("id")) == "domestic-readonly-inspection" and "reachability" in matched_domains:
            score += 20
        recommendations.append({
            "scenario_id": scenario_id,
            "name": scenario.get("name") or scenario_id,
            "name_zh": scenario.get("name_zh") or scenario.get("name") or scenario_id,
            "description": scenario.get("description") or "",
            "description_zh": scenario.get("description_zh") or scenario.get("description") or "",
            "category": scenario.get("category") or "Operations",
            "risk": str(scenario.get("risk") or "low").lower(),
            "platform": resolved_platform,
            "vendor": device.get("vendor") or "",
            "device_id": device_id,
            "device_hostname": device.get("hostname") or device_id,
            "read_only": True,
            "execution_allowed": False,
            "manual_execution_allowed": True,
            "command_count": len(pre_check),
            "matched_domain": matched_domain,
            "reason": "Platform-compatible read-only checks are available; execution still requires an explicit automation workflow." if not matched_domain else f"Matches the incident signal domain: {matched_domain}.",
            "score": score,
        })

    recommendations.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("name") or "")))
    return {
        "incident_id": incident_id_value,
        "device": {
            "id": device_id,
            "hostname": device.get("hostname") or device_id,
            "platform": platform,
            "vendor": device.get("vendor") or "",
        },
        "matched_domains": matched_domains,
        "items": recommendations[:5],
        "policy": {
            "read_only_only": True,
            "automatic_execution": False,
            "manual_execution": True,
            "message": "Only platform-compatible read-only Playbooks are shown. Configuration Playbooks must continue through the change-order approval workflow.",
        },
    }
