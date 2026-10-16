"""Read and paginate unified inspection, Playbook, and backup execution history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection


def _history_timestamp(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Older Playbook rows were written with datetime.now().isoformat(), so
        # they have no offset and represent the backend's configured local TZ.
        # Respect that TZ when comparing records with the UTC 24-hour window.
        return parsed.astimezone().astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def _execution_duration_ms(started_at: Any, ended_at: Any, status: Any) -> int | None:
    started = _history_timestamp(started_at)
    if started is None:
        return None
    ended = _history_timestamp(ended_at)
    if ended is None:
        if str(status or '').strip().lower() != 'running':
            return None
        ended = datetime.now(timezone.utc)
    return max(0, int((ended - started).total_seconds() * 1000))


def get_recent_execution_status_summary(
    *,
    user: dict[str, Any],
    include_playbooks: bool,
    include_backup_runs: bool,
    window_hours: int = 24,
) -> dict[str, Any]:
    """Aggregate visible execution records by actual run status and start time."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    # Stored timestamps include several historical timezone formats. Query a
    # safely wider lexical range, then apply the exact UTC window in Python.
    query_start = (window_start - timedelta(hours=14)).replace(tzinfo=None).isoformat(timespec='seconds')
    rows: list[dict[str, Any]] = []

    conn = get_db_connection()
    try:
        inspection_rows = conn.execute(
            'SELECT started_at, status FROM inspection_runs WHERE started_at >= ?',
            (query_start,),
        ).fetchall()
        rows.extend(dict(row) for row in inspection_rows)

        if include_playbooks:
            playbook_conditions = [
                "NOT (COALESCE(pb.scenario_id, '') = 'instant' "
                "AND COALESCE(pb.scenario_name, '') LIKE 'Config Backup · %')",
                'pb.created_at >= ?',
            ]
            playbook_params: list[Any] = [query_start]
            if user.get('role') != 'Administrator':
                playbook_conditions.append('pb.tenant_id = ?')
                playbook_params.append(str(user.get('tenant_id') or ''))
            playbook_rows = conn.execute(
                'SELECT pb.created_at AS started_at, pb.status AS status '
                'FROM playbook_executions pb WHERE ' + ' AND '.join(playbook_conditions),
                playbook_params,
            ).fetchall()
            rows.extend(dict(row) for row in playbook_rows)

        if include_backup_runs:
            backup_rows = conn.execute(
                '''SELECT r.started_at AS started_at,
                          CASE
                            WHEN LOWER(COALESCE(r.status, '')) = 'running' THEN 'running'
                            WHEN COALESCE(r.failed_count, 0) > 0 AND COALESCE(r.success_count, 0) = 0 THEN 'failed'
                            WHEN COALESCE(r.failed_count, 0) > 0 THEN 'partial_failure'
                            WHEN COALESCE(r.success_count, 0) = 0 AND COALESCE(r.skipped_count, 0) > 0 THEN 'skipped'
                            ELSE 'success'
                          END AS status
                   FROM config_backup_runs r
                   WHERE r.started_at >= ?''',
                (query_start,),
            ).fetchall()
            rows.extend(dict(row) for row in backup_rows)
    finally:
        conn.close()

    summary = {'pending': 0, 'running': 0, 'success': 0, 'abnormal': 0}
    for row in rows:
        started_at = _history_timestamp(row.get('started_at'))
        if started_at is None or started_at < window_start:
            continue
        status = str(row.get('status') or '').strip().lower()
        if status in {'pending', 'queued', 'awaiting_approval', 'awaiting approval', 'approval_pending', 'scheduled'}:
            summary['pending'] += 1
        elif status in {'running', 'in_progress', 'in progress', 'processing', 'executing'}:
            summary['running'] += 1
        elif status in {'success', 'succeeded', 'completed', 'complete'}:
            summary['success'] += 1
        else:
            summary['abnormal'] += 1

    return {
        **summary,
        'total': sum(summary.values()),
        'window_hours': window_hours,
        'window_started_at': window_start.isoformat(timespec='seconds'),
        'generated_at': now.isoformat(timespec='seconds'),
    }


def get_execution_history(
    *,
    page: int,
    page_size: int,
    trigger_type: str,
    query: str,
    user: dict[str, Any],
    include_playbooks: bool,
    include_backup_runs: bool,
) -> dict[str, Any]:
    """Return one globally ordered page across the authorized execution sources."""
    inspection_select = '''
        SELECT
            ir.id AS id,
            'inspection' AS source,
            ir.started_at AS started_at,
            ir.completed_at AS ended_at,
            CASE WHEN ir.trigger_type = 'manual' THEN 'manual' ELSE 'plan' END AS trigger_type,
            ir.status AS status,
            COALESCE(ir.total_devices, 0) AS total_devices,
            NULL AS device_ids,
            COALESCE(ir.success_count, 0) AS success_count,
            COALESCE(ir.failed_count, 0) AS failed_count,
            0 AS partial_count,
            0 AS skipped_count,
            COALESCE(NULLIF(TRIM(job.created_by), ''), NULLIF(TRIM(ir.created_by), ''), 'system') AS created_by,
            COALESCE(NULLIF(TRIM(ins.name), ''), NULLIF(TRIM(job.name), '')) AS name,
            COALESCE(
                NULLIF(TRIM(ins.name), ''),
                NULLIF(TRIM(job.name), ''),
                'Network Inspection 网络巡检'
            ) AS search_name
        FROM inspection_runs ir
        LEFT JOIN inspection_schedules ins ON ins.id = ir.schedule_id
        LEFT JOIN scheduled_jobs job
            ON ir.schedule_id IS NULL
            AND ir.created_by LIKE 'scheduler:%'
            AND job.id = SUBSTR(ir.created_by, 11)
    '''
    source_selects = [inspection_select]
    source_params: list[Any] = []

    if include_playbooks:
        playbook_conditions = [
            "NOT (COALESCE(pb.scenario_id, '') = 'instant' "
            "AND COALESCE(pb.scenario_name, '') LIKE 'Config Backup · %')"
        ]
        if user.get('role') != 'Administrator':
            # Match GET /api/playbooks: tenant users cannot see unassociated rows.
            playbook_conditions.append('pb.tenant_id = ?')
            source_params.append(str(user.get('tenant_id') or ''))
        playbook_where = 'WHERE ' + ' AND '.join(playbook_conditions)
        source_selects.append(f'''
            SELECT
                pb.id AS id,
                'playbook' AS source,
                pb.created_at AS started_at,
                CASE
                    WHEN LOWER(COALESCE(pb.status, '')) IN ('running', 'pending', 'awaiting_approval') THEN NULL
                    ELSE pb.updated_at
                END AS ended_at,
                CASE
                    WHEN pb.author IN ('scheduler', 'system')
                         OR COALESCE(pb.scenario_id, '') LIKE 'scheduled:%'
                    THEN 'job'
                    ELSE 'manual'
                END AS trigger_type,
                pb.status AS status,
                COALESCE(pb.total_devices, 0) AS total_devices,
                pb.device_ids AS device_ids,
                COALESCE(pb.success_count, 0) AS success_count,
                COALESCE(pb.failed_count, 0) AS failed_count,
                COALESCE(pb.partial_count, 0) AS partial_count,
                0 AS skipped_count,
                COALESCE(NULLIF(TRIM(scheduled_job.created_by), ''), NULLIF(TRIM(pb.author), ''), 'admin') AS created_by,
                NULLIF(TRIM(pb.scenario_name), '') AS name,
                COALESCE(NULLIF(TRIM(pb.scenario_name), ''), 'Quick Playbook 快捷命令执行') AS search_name
            FROM playbook_executions pb
            LEFT JOIN scheduled_jobs scheduled_job
                ON COALESCE(pb.scenario_id, '') LIKE 'scheduled:%'
               AND scheduled_job.id = SUBSTR(pb.scenario_id, 11)
            {playbook_where}
        ''')

    if include_backup_runs:
        source_selects.append('''
            SELECT
                r.id AS id,
                'config_backup' AS source,
                r.started_at AS started_at,
                r.finished_at AS ended_at,
                CASE
                    WHEN LOWER(COALESCE(r.trigger, '')) = 'manual' THEN 'manual'
                    ELSE 'job'
                END AS trigger_type,
                CASE
                    WHEN r.status = 'running' THEN 'running'
                    WHEN COALESCE(r.failed_count, 0) > 0 AND COALESCE(r.success_count, 0) = 0 THEN 'failed'
                    WHEN COALESCE(r.failed_count, 0) > 0 THEN 'partial_failure'
                    WHEN COALESCE(r.success_count, 0) = 0 AND COALESCE(r.skipped_count, 0) > 0 THEN 'skipped'
                    ELSE 'success'
                END AS status,
                COALESCE(r.total_devices, 0) AS total_devices,
                NULL AS device_ids,
                COALESCE(r.success_count, 0) AS success_count,
                COALESCE(r.failed_count, 0) AS failed_count,
                0 AS partial_count,
                COALESCE(r.skipped_count, 0) AS skipped_count,
                COALESCE(r.author, 'system') AS created_by,
                'Config Backup · ' || COALESCE(
                    NULLIF(TRIM(backup_policy.name), ''),
                    NULLIF(TRIM(r.trigger), ''),
                    'backup'
                ) AS name,
                'Config Backup · ' || COALESCE(
                    NULLIF(TRIM(backup_policy.name), ''),
                    NULLIF(TRIM(r.trigger), ''),
                    'backup'
                ) AS search_name
            FROM config_backup_runs r
            LEFT JOIN config_backup_policies backup_policy ON backup_policy.id = r.policy_id
        ''')

    where_clauses: list[str] = []
    filter_params: list[Any] = []
    if trigger_type != 'all':
        where_clauses.append('trigger_type = ?')
        filter_params.append(trigger_type)
    search_text = query.strip().lower()
    if search_text:
        like_query = f'%{search_text}%'
        where_clauses.append(
            "(LOWER(search_name) LIKE ? OR LOWER(COALESCE(created_by, '')) LIKE ? "
            "OR LOWER(COALESCE(status, '')) LIKE ?)"
        )
        filter_params.extend((like_query, like_query, like_query))
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
    history_sql = ' UNION ALL '.join(source_selects)
    offset = (page - 1) * page_size

    conn = get_db_connection()
    try:
        total_row = conn.execute(
            f'WITH history AS ({history_sql}) SELECT COUNT(*) FROM history {where_sql}',
            [*source_params, *filter_params],
        ).fetchone()
        total = int(total_row[0] if total_row else 0)
        rows = conn.execute(
            f'''WITH history AS ({history_sql})
                SELECT id, source, started_at, ended_at, trigger_type, status,
                       total_devices, device_ids, success_count, failed_count, partial_count, skipped_count,
                       created_by, name
                FROM history
                {where_sql}
                ORDER BY CAST(NULLIF(started_at, '') AS TIMESTAMPTZ) DESC NULLS LAST,
                         source ASC, id DESC
                LIMIT ? OFFSET ?''',
            [*source_params, *filter_params, page_size, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            device_ids = item.pop('device_ids', None)
            if item['source'] == 'playbook' and not item.get('total_devices'):
                try:
                    item['total_devices'] = len(json.loads(device_ids or '[]'))
                except (TypeError, ValueError):
                    item['total_devices'] = 0
            item['duration_ms'] = _execution_duration_ms(
                item.get('started_at'), item.get('ended_at'), item.get('status')
            )
            items.append(item)
        return {
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()
