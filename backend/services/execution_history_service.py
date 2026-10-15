"""Read and paginate unified inspection, Playbook, and backup execution history."""

from __future__ import annotations

import json
from typing import Any

from database import get_db_connection


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
            CASE WHEN ir.trigger_type = 'manual' THEN 'manual' ELSE 'plan' END AS trigger_type,
            ir.status AS status,
            COALESCE(ir.total_devices, 0) AS total_devices,
            NULL AS device_ids,
            COALESCE(ir.success_count, 0) AS success_count,
            COALESCE(ir.failed_count, 0) AS failed_count,
            0 AS partial_count,
            0 AS skipped_count,
            ir.avg_health_score AS avg_health_score,
            COALESCE(ir.created_by, 'system') AS created_by,
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
                NULL AS avg_health_score,
                COALESCE(pb.author, 'admin') AS created_by,
                NULLIF(TRIM(pb.scenario_name), '') AS name,
                COALESCE(NULLIF(TRIM(pb.scenario_name), ''), 'Quick Playbook 快捷命令执行') AS search_name
            FROM playbook_executions pb
            {playbook_where}
        ''')

    if include_backup_runs:
        source_selects.append('''
            SELECT
                r.id AS id,
                'config_backup' AS source,
                r.started_at AS started_at,
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
                NULL AS avg_health_score,
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
                SELECT id, source, started_at, trigger_type, status,
                       total_devices, device_ids, success_count, failed_count, partial_count, skipped_count,
                       avg_health_score, created_by, name
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
            items.append(item)
        return {
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()
