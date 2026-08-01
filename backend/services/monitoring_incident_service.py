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
                        CASE WHEN COALESCE(d.site, '') LIKE 'site-%' THEN '' ELSE COALESCE(d.site, '') END,
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
                        CASE WHEN COALESCE(d.site, '') LIKE 'site-%' THEN '' ELSE COALESCE(d.site, '') END,
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
    try:
        work_order_rows = conn.execute(
            "SELECT id, order_number, title, status FROM change_orders "
            "WHERE incident_id = ? ORDER BY created_at DESC",
            (incident_id_value,),
        ).fetchall()
        item["work_orders"] = [dict(work_order) for work_order in work_order_rows]
    except Exception:
        # Keep incident reads compatible with databases that have not applied
        # the optional work-order link migration yet.
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
            f"SELECT id, hostname, ip_address, site FROM devices WHERE id IN ({placeholders})",
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
                f"SELECT id, hostname, ip_address, site FROM devices WHERE id IN ({neighbor_placeholders})",
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
    site_names = sorted({str(node.get("site") or "") for node in nodes if node.get("site")})
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
            "confidence": "high" if root_alert and links else "medium" if root_alert or links else "low",
            "evidence": evidence,
            "disclaimer": "Inference is evidence-based and must be confirmed by an operator.",
        },
        "business_impact": {
            "sites": site_names,
            "services": [],
            "business_units": [],
            "confidence": "low",
            "data_gaps": ["No CMDB service/business-owner mapping is configured for the affected devices."],
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
