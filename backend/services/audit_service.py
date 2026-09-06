import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection


AUDIT_OPEN_STATUSES = {"open", "investigating", "accepted"}
_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "token", "secret", "private_key", "community",
    "authorization", "credential", "api_key",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def redact_audit_value(value: Any, key: str = "") -> Any:
    """Recursively remove credentials and tokens before persistence."""
    lowered = key.lower()
    if key and any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_audit_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_audit_value(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(redact_audit_value(value or {}), ensure_ascii=True, default=str)


def log_audit_event(
    *,
    event_type: str,
    category: str,
    severity: str,
    status: str,
    summary: str,
    actor_id: str | None = None,
    actor_username: str | None = None,
    actor_role: str | None = None,
    source_ip: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    device_id: str | None = None,
    job_id: str | None = None,
    execution_id: str | None = None,
    snapshot_id: str | None = None,
    request_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    conn=None,
) -> str:
    event_id = str(uuid.uuid4())
    created_at = utc_now_iso()
    own_conn = conn is None
    if own_conn:
        conn = get_db_connection()
    try:
        conn.execute(
            '''
            INSERT INTO audit_events (
                id, event_type, category, severity, status,
                actor_id, actor_username, actor_role, source_ip,
                target_type, target_id, target_name,
                device_id, job_id, execution_id, snapshot_id,
                summary, details_json, request_id, before_json, after_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                event_id,
                event_type,
                category,
                severity,
                status,
                str(actor_id) if actor_id is not None else None,
                actor_username or "system",
                actor_role or "system",
                source_ip,
                target_type,
                target_id,
                target_name,
                device_id,
                job_id,
                execution_id,
                snapshot_id,
                summary,
                _json_dumps(details),
                request_id or "",
                _json_dumps(before),
                _json_dumps(after),
                created_at,
            ),
        )
        if own_conn:
            conn.commit()
        return event_id
    finally:
        if own_conn:
            conn.close()


def list_audit_events(
    *,
    category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    time_range: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if category and category != "all":
        where_clauses.append("category = ?")
        params.append(category)
    if severity and severity != "all":
        where_clauses.append("severity = ?")
        params.append(severity)
    if status and status != "all":
        where_clauses.append("status = ?")
        params.append(status)
    if time_range and time_range != "all":
        _delta = {'24h': 1, '7d': 7, '30d': 30}.get(time_range)
        if _delta:
            _cutoff = (datetime.now(timezone.utc) - timedelta(days=_delta)).isoformat()
            where_clauses.append("created_at >= ?")
            params.append(_cutoff)
    if search and search.strip():
        q = f"%{search.strip()}%"
        where_clauses.append("(summary LIKE ? OR target_name LIKE ? OR actor_username LIKE ? OR event_type LIKE ?)")
        params.extend([q, q, q, q])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    offset = (page - 1) * page_size

    conn = get_db_connection()
    try:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS count FROM audit_events {where_sql}", tuple(params)
        ).fetchone()
        total = int(total_row["count"]) if total_row else 0

        rows = conn.execute(
            f'''
            SELECT * FROM audit_events
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            ''',
            tuple([*params, page_size, offset]),
        ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item.get("details_json") or "{}")
            except Exception:
                item["details"] = {}
            for json_field, output_field in (("before_json", "before"), ("after_json", "after")):
                try:
                    item[output_field] = json.loads(item.get(json_field) or "{}")
                except Exception:
                    item[output_field] = {}
            items.append(item)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        conn.close()


def get_audit_event(event_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["details"] = json.loads(item.get("details_json") or "{}")
        except Exception:
            item["details"] = {}
        for json_field, output_field in (("before_json", "before"), ("after_json", "after")):
            try:
                item[output_field] = json.loads(item.get(json_field) or "{}")
            except Exception:
                item[output_field] = {}
        return item
    finally:
        conn.close()
