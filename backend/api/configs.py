"""
configs.py - Config Snapshot API
Stores config files in: backup/YYYY/MM/Vendor/Hostname/YYYYMMDD_HHMMSS_trigger.cfg
Stores metadata in the configured database table config_snapshots.
"""

import os
import uuid
import json
import gzip
import logging
import hashlib
import re
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from database import get_db_connection
from services.audit_service import log_audit_event
from core.config import settings
from core.scheduler_manager import scheduler
from apscheduler.triggers.cron import CronTrigger
from services import config_backup_policy_service
from services.config_search_service import redact_config_line

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _config_archive_name(run_id: object = "") -> str:
    """Build a collision-resistant, time-based name for a remote ZIP bundle."""

    safe_run_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(run_id or "")).strip("-_")[-24:]
    suffix = f"_{safe_run_id}" if safe_run_id else f"_{uuid.uuid4().hex[:8]}"
    return f"config_backup_{_utc_now().strftime('%Y%m%d_%H%M%S')}{suffix}.zip"


def _build_device_scope_tree(rows: list[dict]) -> list[dict]:
    """Build the CMDB-compatible site/type/category/role hierarchy."""
    root = {
        "id": "root",
        "kind": "root",
        "label": "All assets",
        "count": 0,
        "branch": {},
        "children": [],
    }

    def find_or_create(parent: dict, node_id: str, kind: str, label: str, branch: dict, count: int) -> dict:
        node = next((item for item in parent["children"] if item["id"] == node_id), None)
        if node is None:
            node = {"id": node_id, "kind": kind, "label": label or "Unassigned", "count": 0, "branch": branch, "children": []}
            parent["children"].append(node)
        node["count"] += count
        return node

    for row in rows:
        site_id = str(row.get("site_id") or "unassigned")
        site_name = str(row.get("site_name") or row.get("site_code") or "Unassigned site")
        asset_type = str(row.get("asset_type") or "network_device")
        category = str(row.get("device_category") or "other")
        role = str(row.get("device_role") or "unassigned")
        root["count"] += 1
        site = find_or_create(root, f"site:{site_id}", "site", site_name, {"site_id": site_id}, 1)
        asset = find_or_create(site, f"{site['id']}:type:{asset_type}", "type", asset_type, {"site_id": site.get("branch", {}).get("site_id", ""), "asset_type": asset_type}, 1)
        device_category = find_or_create(asset, f"{asset['id']}:category:{category}", "category", category, {"site_id": site.get("branch", {}).get("site_id", ""), "asset_type": asset_type, "device_category": category}, 1)
        find_or_create(device_category, f"{device_category['id']}:role:{role}", "role", role, {"site_id": site.get("branch", {}).get("site_id", ""), "asset_type": asset_type, "device_category": category, "device_role": "" if role == "unassigned" else role}, 1)
    return [root]

# Backup root directory - relative to cwd (d:\nexora-automation)
BACKUP_ROOT = os.path.join(os.getcwd(), 'backup')


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────

class SnapshotCreate(BaseModel):
    device_id: str
    hostname: str
    vendor: str
    content: str
    trigger: str = 'manual'
    author: str = 'admin'
    tag: str = ''


class ScheduleUpdate(BaseModel):
    enabled: bool
    cron: str = '0 2 * * *'          # 标准 5 段 cron
    # 兼容旧字段（前端平滑迁移后可移除）
    hour: int | None = None
    minute: int | None = None


def _normalize_config_content(content: str) -> str:
    """Normalize volatile whitespace/timestamps while preserving configuration order."""
    normalized_lines = []
    volatile_patterns = (
        re.compile(r'^\s*!?\s*(last configuration change|current configuration|time source is)', re.I),
        re.compile(r'^\s*#\s*(last commit|generated at)', re.I),
        re.compile(r'^\s*(?:return|end)\s*$', re.I),
        re.compile(r'^\s*(?:<[A-Za-z0-9_.:-]{1,128}>?|\[[A-Za-z0-9_.:-]{1,128}\]?)\s*$', re.I),
        re.compile(r'^\s*[A-Za-z0-9_.:-]+(?:\([^)]*\))?[#>]\s*$', re.I),
    )
    for raw_line in str(content or '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        line = raw_line.rstrip()
        if any(pattern.search(line) for pattern in volatile_patterns):
            continue
        # Blank lines are CLI formatting noise and must not create a new
        # snapshot when the device configuration itself is unchanged.
        if not line.strip():
            continue
        # Secret presentation can vary between collectors (for example
        # ``password cipher`` vs ``password <redacted>``); compare the safe
        # representation so that credential formatting is not reported as a
        # configuration change.
        normalized_lines.append(redact_config_line(line))
    return '\n'.join(normalized_lines).strip() + '\n'


def _config_snapshot_metadata(content: str) -> dict:
    raw = str(content or '')
    normalized = _normalize_config_content(raw)
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    non_empty = [line for line in lines if line.strip()]
    error_markers = (
        '% invalid input',
        '% authorization failed',
        'permission denied',
        'command not found',
        'connection timed out',
    )
    truncation_reason = ''
    if not non_empty:
        truncation_reason = 'empty_output'
    elif any(marker in raw.lower() for marker in error_markers):
        truncation_reason = 'command_error_output'
    elif len(raw.encode('utf-8')) < 64 or len(non_empty) < 3:
        truncation_reason = 'suspiciously_short'
    integrity_status = 'invalid' if truncation_reason else 'verified'
    section_count = sum(
        1 for line in non_empty
        if line == line.lstrip() and not line.startswith(('!', '#', 'Building configuration'))
    )
    return {
        'raw_hash': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        'normalized_hash': hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
        'line_count': len(lines),
        'section_count': section_count,
        'integrity_status': integrity_status,
        'lifecycle_status': 'fingerprinted' if integrity_status == 'verified' else 'stored_raw',
        'normalizer_version': 'ncm-v3',
        'truncation_reason': truncation_reason,
    }


# ──────────────────────────────────────────────
# File helpers
# ──────────────────────────────────────────────

def _resolve_backup_dir(vendor: str, hostname: str, ts: datetime) -> str:
    """Return absolute path to the directory for a snapshot."""
    return os.path.join(
        BACKUP_ROOT,
        ts.strftime('%Y'),
        ts.strftime('%m'),
        vendor or 'Unknown',
        hostname or 'Unknown',
    )


def _write_config_file(vendor: str, hostname: str, ts: datetime, trigger: str, content: str, config_type: str = 'running') -> str:
    """Write config to disk (gzip compressed, optionally encrypted); return relative file path from BACKUP_ROOT."""
    dir_path = _resolve_backup_dir(vendor, hostname, ts)
    os.makedirs(dir_path, exist_ok=True)
    suffix = "_startup" if config_type == "startup" else ""
    filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{trigger}{suffix}.cfg"
    abs_path = os.path.join(dir_path, filename)
    data = gzip.compress(content.encode('utf-8'))
    # Configuration snapshots are raw sensitive output; fail closed if the
    # application key is unavailable instead of writing a plaintext archive.
    try:
        from core.crypto import _get_fernet
        f = _get_fernet()
        data = b'ENCRYPTED:' + f.encrypt(data)
    except Exception as exc:
        raise RuntimeError('CONFIG_BACKUP_ENCRYPTION_UNAVAILABLE') from exc
    with open(abs_path, 'wb') as fh:
        fh.write(data)
    return os.path.relpath(abs_path, BACKUP_ROOT).replace(os.sep, '/')


def _read_config_file(file_path: str) -> str:
    # Normalise separators so paths saved on Windows work on Linux and vice versa
    abs_path = os.path.join(BACKUP_ROOT, file_path.replace('/', os.sep).replace('\\', os.sep))
    if not os.path.exists(abs_path):
        return ''
    with open(abs_path, 'rb') as fh:
        data = fh.read()
    if data.startswith(b'ENCRYPTED:'):
        try:
            from core.crypto import _get_fernet
            f = _get_fernet()
            data = f.decrypt(data[len(b'ENCRYPTED:'):])
        except Exception:
            logger.error(f"Failed to decrypt config file: {file_path}")
            return ''
    # Detect gzip compression (magic bytes \x1f\x8b)
    if data[:2] == b'\x1f\x8b':
        try:
            data = gzip.decompress(data)
        except Exception:
            logger.warning(f"Failed to decompress config file: {file_path}")
    return data.decode('utf-8')


def _delete_config_file(file_path: str):
    abs_path = os.path.join(BACKUP_ROOT, file_path.replace('/', os.sep).replace('\\', os.sep))
    if os.path.exists(abs_path):
        os.remove(abs_path)
    # Clean up empty parent dirs (up to BACKUP_ROOT)
    parent = os.path.dirname(abs_path)
    for _ in range(4):  # hostname / vendor / month / year
        if parent == BACKUP_ROOT:
            break
        try:
            os.rmdir(parent)  # only removes if empty
        except OSError:
            break
        parent = os.path.dirname(parent)


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return dict(row)


def _create_backup_run(
    run_id: str,
    *,
    trigger: str,
    author: str,
    devices: list,
    eligible_ids: set[str],
    policy_id: str = '',
    policy_snapshot: str = '',
) -> dict[str, str]:
    """Persist a run and its planned device outcomes before network work starts."""
    now = _utc_now_iso()
    device_rows: dict[str, str] = {}
    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO config_backup_runs
               (id, trigger, author, status, started_at, total_devices,
                success_count, failed_count, skipped_count, policy_id,
                policy_snapshot, created_at)
               VALUES (?, ?, ?, 'running', ?, ?, 0, 0, ?, ?, ?, ?)''',
            (run_id, trigger, author, now, len(devices),
             len(devices) - len(eligible_ids), policy_id, policy_snapshot, now),
        )
        for device in devices:
            device_id = str(device['id'])
            row_id = f"run-device-{uuid.uuid4().hex[:16]}"
            eligible = device_id in eligible_ids
            conn.execute(
                '''INSERT INTO config_backup_run_devices
                   (id, run_id, device_id, hostname, ip_address, platform, status,
                    reason, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    row_id,
                    run_id,
                    device_id,
                    device['hostname'] or '',
                    device['ip_address'] or '',
                    device['platform'] or '',
                    'pending' if eligible else 'skipped',
                    '' if eligible else 'not_eligible',
                    now,
                ),
            )
            device_rows[device_id] = row_id
        conn.commit()
    finally:
        conn.close()
    return device_rows


def _record_backup_run_device(
    row_id: str,
    *,
    result: dict,
    finished_at: str,
    duration_ms: int,
) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            '''UPDATE config_backup_run_devices
               SET status = ?, reason = ?, detail = ?, snapshot_id = ?,
                   finished_at = ?, duration_ms = ?
               WHERE id = ?''',
            (
                result.get('status') or 'unknown',
                result.get('reason') or '',
                result.get('detail') or '',
                result.get('snapshot_id') or None,
                finished_at,
                duration_ms,
                row_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _finish_backup_run(
    run_id: str,
    *,
    error_message: str = '',
    tftp_status: str = 'none',
    tftp_server: str = '',
    tftp_log: str = '',
    tftp_uploaded_count: int = 0,
) -> None:
    conn = get_db_connection()
    try:
        counts = conn.execute(
            '''SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                 SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
               FROM config_backup_run_devices WHERE run_id = ?''',
            (run_id,),
        ).fetchone()
        total = int(counts['total'] or 0)
        success_count = int(counts['success_count'] or 0)
        failed_count = int(counts['failed_count'] or 0)
        skipped_count = int(counts['skipped_count'] or 0)
        status = 'completed' if failed_count == 0 else 'partial'
        conn.execute(
            '''UPDATE config_backup_runs
               SET status = ?, finished_at = ?, total_devices = ?,
                   success_count = ?, failed_count = ?, skipped_count = ?,
                   error_message = ?,
                   tftp_status = ?, tftp_server = ?, tftp_log = ?, tftp_uploaded_count = ?
               WHERE id = ?''',
            (
                status,
                _utc_now_iso(),
                total,
                success_count,
                failed_count,
                skipped_count,
                error_message,
                tftp_status,
                tftp_server,
                tftp_log,
                tftp_uploaded_count,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get('/configs/devices-with-backups')
def list_devices_with_backups(
    search: str = Query(default='', description='Search hostname or IP'),
    site_id: str = Query(default='', description='Filter by site'),
    asset_type: str = Query(default='', description='Filter by asset type'),
    device_category: str = Query(default='', description='Filter by device category'),
    device_role: str = Query(default='', description='Filter by device role'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    """Return devices eligible for config backup, with backup count and pagination.

    Scope:
      - Only network devices (platforms: cisco_*, arista, juniper_*, huawei_*,
        h3c_*, ruijie_*). Linux / server assets are excluded because they
        don't produce a textual running-config.
      - Includes devices with 0 snapshots so operators can trigger a first
        backup from the UI.
    """
    conn = get_db_connection()
    try:
        # Platform whitelist — keep in sync with run_scheduled_backup().
        platform_keywords = [
            'cisco', 'arista', 'rgos', 'ruijie', 'juniper',
            'junos', 'huawei', 'vrp', 'h3c', 'comware',
        ]
        platform_conditions = " OR ".join(
            "LOWER(COALESCE(d.platform,'')) LIKE ?" for _ in platform_keywords
        )
        platform_params = [f"%{kw}%" for kw in platform_keywords]

        where_sql = f"WHERE ({platform_conditions})"
        params: list = list(platform_params)
        if site_id:
            site_expr = "COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), '')"
            if site_id == 'unassigned':
                where_sql += f" AND {site_expr} = ''"
            else:
                where_sql += f" AND {site_expr} = ?"
                params.append(site_id)
        if asset_type:
            where_sql += " AND COALESCE(NULLIF(pa.asset_type, ''), 'network_device') = ?"
            params.append(asset_type)
        if device_category:
            where_sql += " AND COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') = ?"
            params.append(device_category)
        if device_role:
            where_sql += " AND COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') = ?"
            params.append(device_role)
        if search and search.strip():
            fuzzy = f"%{search.strip().lower()}%"
            where_sql += " AND (LOWER(d.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ? OR LOWER(COALESCE(s.site_name, '')) LIKE ?)"
            params.extend([fuzzy, fuzzy, fuzzy])

        joins_sql = """
            LEFT JOIN physical_assets pa ON pa.id = d.asset_id
            LEFT JOIN sites s ON (
                s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''))
                OR (COALESCE(d.site_id, '') = '' AND (s.site_code = d.site OR s.site_name = d.site))
            )
        """

        count_sql = f'''
            SELECT COUNT(DISTINCT d.id)
            FROM devices d
            {joins_sql}
            {where_sql}
        '''
        total = conn.execute(count_sql, tuple(params)).fetchone()[0]

        offset = (page - 1) * page_size
        # Devices sorted by whether they've been backed up (backed-up first),
        # then by most recent backup time, then by hostname.
        all_rows = conn.execute(f'''
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.status,
                   COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), NULLIF(d.site, ''), '') AS site_id,
                   COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''), 'Unassigned site') AS site_name,
                   COALESCE(NULLIF(s.site_code, ''), '') AS site_code,
                   COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS asset_type,
                   COALESCE(NULLIF(pa.device_category, ''), NULLIF(d.device_category, ''), 'other') AS device_category,
                   COALESCE(NULLIF(pa.device_role, ''), NULLIF(d.role, ''), 'unassigned') AS device_role,
                   COUNT(cs.id) AS backup_count,
                   MAX(cs.timestamp) AS latest_backup
            FROM devices d
            {joins_sql}
            LEFT JOIN config_snapshots cs ON cs.device_id = d.id
            {where_sql}
            GROUP BY d.id, d.hostname, d.ip_address, d.platform, d.status, d.site_id, d.site,
                     s.site_name, s.site_code, pa.site_id, pa.asset_type, pa.device_category,
                     pa.device_role, d.device_category, d.role
            ORDER BY
                CASE WHEN COUNT(cs.id) > 0 THEN 0 ELSE 1 END,
                COALESCE(MAX(cs.timestamp), '') DESC,
                d.hostname
        ''', tuple(params)).fetchall()
        rows = all_rows[offset:offset + page_size]

        return {
            'items': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
            'tree': _build_device_scope_tree([dict(r) for r in all_rows]),
        }
    finally:
        conn.close()


@router.get('/configs/snapshots')
def list_snapshots(
    device_id: str = None,
    hostname: str = None,
    ip_address: str = None,
    config_type: str = Query(default=None, description="Filter by config_type: running | startup"),
    q: str = None,
):
    """List all snapshot metadata (no content)."""
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if device_id:
            where_clauses.append('cs.device_id = ?')
            params.append(device_id)

        if config_type and config_type.strip() and config_type.strip().lower() != 'all':
            where_clauses.append('cs.config_type = ?')
            params.append(config_type.strip().lower())

        if hostname and hostname.strip():
            where_clauses.append('LOWER(cs.hostname) LIKE ?')
            params.append(f"%{hostname.strip().lower()}%")

        if ip_address and ip_address.strip():
            where_clauses.append("LOWER(COALESCE(d.ip_address, '')) LIKE ?")
            params.append(f"%{ip_address.strip().lower()}%")

        if q and q.strip():
            fuzzy = f"%{q.strip().lower()}%"
            where_clauses.append("(LOWER(cs.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)")
            params.extend([fuzzy, fuzzy])

        sql = '''
            SELECT cs.*, d.ip_address
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
        '''
        if where_clauses:
            sql += ' WHERE ' + ' AND '.join(where_clauses)
        sql += ' ORDER BY cs.timestamp DESC'

        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


@router.get('/configs/latest-backups')
def list_latest_backups(
    search: str = Query(default='', description='Search hostname or IP'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Return the latest config backup per device with pagination."""
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if search and search.strip():
            fuzzy = f"%{search.strip().lower()}%"
            where_clauses.append("(LOWER(d.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)")
            params.extend([fuzzy, fuzzy])

        filter_sql = ''
        if where_clauses:
            filter_sql = ' AND ' + ' AND '.join(where_clauses)

        count_sql = f'''
            SELECT COUNT(*)
            FROM devices d
            WHERE 1=1 {filter_sql}
        '''
        total = conn.execute(count_sql, tuple(params)).fetchone()[0]

        offset = (page - 1) * page_size
        data_sql = f'''
            SELECT d.id AS device_id, d.hostname, d.vendor, d.ip_address, d.status AS device_status,
                   d.platform, cs.id AS snapshot_id, cs.timestamp, cs.size, cs.trigger,
                   cs.raw_hash, cs.normalized_hash, cs.line_count, cs.section_count,
                   cs.integrity_status, cs.lifecycle_status
            FROM devices d
            LEFT JOIN (
                SELECT cs1.*
                FROM config_snapshots cs1
                INNER JOIN (
                    SELECT device_id, MAX(timestamp) AS max_ts
                    FROM config_snapshots GROUP BY device_id
                ) cs2 ON cs1.device_id = cs2.device_id AND cs1.timestamp = cs2.max_ts
            ) cs ON d.id = cs.device_id
            WHERE 1=1 {filter_sql}
            ORDER BY CASE WHEN cs.timestamp IS NULL THEN 1 ELSE 0 END, cs.timestamp DESC, d.hostname ASC
            LIMIT ? OFFSET ?
        '''
        rows = conn.execute(data_sql, tuple([*params, page_size, offset])).fetchall()

        items = []
        for r in rows:
            items.append({
                'id': r['snapshot_id'] or '',
                'device_id': r['device_id'],
                'hostname': r['hostname'],
                'ip_address': r['ip_address'] or '',
                'vendor': r['vendor'] or '',
                'platform': r['platform'] or '',
                'device_status': r['device_status'] or 'unknown',
                'trigger': r['trigger'] or '',
                'timestamp': r['timestamp'] or '',
                'size': r['size'] or 0,
                'raw_hash': r['raw_hash'] or '',
                'normalized_hash': r['normalized_hash'] or '',
                'line_count': r['line_count'] or 0,
                'section_count': r['section_count'] or 0,
                'integrity_status': r['integrity_status'] or 'unknown',
                'lifecycle_status': r['lifecycle_status'] or 'stored_raw',
            })

        return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
    finally:
        conn.close()


@router.get('/configs/backup-runs')
def list_backup_runs(
    device_id: str = Query(default=''),
    date: str = Query(default='', description='Filter batches by start date (YYYY-MM-DD)'),
    start_date: str = Query(default='', description='Inclusive start date (YYYY-MM-DD)'),
    end_date: str = Query(default='', description='Inclusive end date (YYYY-MM-DD)'),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """Return persisted backup batches for audit/history views."""
    conn = get_db_connection()
    try:
        where = []
        params: list = []
        if device_id.strip():
            where.append(
                "EXISTS (SELECT 1 FROM config_backup_run_devices rd "
                "WHERE rd.run_id = r.id AND rd.device_id = ?)"
            )
            params.append(device_id.strip())
        start_date_filter = (start_date.strip() or date.strip())
        end_date_filter = (end_date.strip() or date.strip())
        parsed_dates = []
        for date_filter in (start_date_filter, end_date_filter):
            if not date_filter:
                parsed_dates.append(None)
                continue
            try:
                parsed_date = datetime.strptime(date_filter, '%Y-%m-%d')
            except ValueError as exc:
                raise HTTPException(status_code=400, detail='date must use YYYY-MM-DD') from exc
            if parsed_date.strftime('%Y-%m-%d') != date_filter:
                raise HTTPException(status_code=400, detail='date must use YYYY-MM-DD')
            if parsed_date.date() > datetime.now(timezone.utc).date():
                raise HTTPException(status_code=400, detail='backup date cannot be in the future')
            parsed_dates.append(parsed_date)
        if parsed_dates[0] and parsed_dates[1] and parsed_dates[0] > parsed_dates[1]:
            raise HTTPException(status_code=400, detail='start_date must be before or equal to end_date')
        if start_date_filter:
            where.append("SUBSTR(r.started_at, 1, 10) >= ?")
            params.append(start_date_filter)
        if end_date_filter:
            where.append("SUBSTR(r.started_at, 1, 10) <= ?")
            params.append(end_date_filter)
        where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM config_backup_runs r{where_sql}",
            tuple(params),
        ).fetchone()['c']
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''SELECT r.id, r.trigger, r.author, r.status, r.started_at, r.finished_at,
                       r.total_devices, r.success_count, r.failed_count, r.skipped_count,
                       r.policy_id, r.policy_snapshot, r.error_message
                FROM config_backup_runs r{where_sql}
                ORDER BY r.started_at DESC LIMIT ? OFFSET ?''',
            tuple([*params, page_size, offset]),
        ).fetchall()
        run_ids = [row['id'] for row in rows]
        site_summary_map: dict[str, list[dict]] = {run_id: [] for run_id in run_ids}
        if run_ids:
            placeholders = ','.join('?' for _ in run_ids)
            site_rows = conn.execute(
                f'''SELECT rd.run_id,
                           COALESCE(NULLIF(TRIM(s.site_name), ''), NULLIF(TRIM(s.site_code), ''), NULLIF(TRIM(d.site), ''), 'Unassigned') AS site,
                           COUNT(*) AS total,
                           SUM(CASE WHEN rd.status = 'success' THEN 1 ELSE 0 END) AS success,
                           SUM(CASE WHEN rd.status = 'failed' THEN 1 ELSE 0 END) AS failed,
                           SUM(CASE WHEN rd.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                           SUM(CASE WHEN rd.status IS NULL OR rd.status NOT IN ('success', 'failed', 'skipped') THEN 1 ELSE 0 END) AS unknown
                    FROM config_backup_run_devices rd
                    LEFT JOIN devices d ON d.id = rd.device_id
                    LEFT JOIN sites s ON s.id = d.site_id
                              OR (COALESCE(NULLIF(TRIM(d.site_id), ''), '') = ''
                                  AND (s.id = d.site OR s.site_code = d.site OR s.site_name = d.site))
                    WHERE rd.run_id IN ({placeholders})
                    GROUP BY rd.run_id, COALESCE(NULLIF(TRIM(s.site_name), ''), NULLIF(TRIM(s.site_code), ''), NULLIF(TRIM(d.site), ''), 'Unassigned')
                    ORDER BY rd.run_id, site''',
                tuple(run_ids),
            ).fetchall()
            for site_row in site_rows:
                site_summary_map[site_row['run_id']].append({
                    'site': site_row['site'] or 'Unassigned',
                    'total': int(site_row['total'] or 0),
                    'success': int(site_row['success'] or 0),
                    'failed': int(site_row['failed'] or 0),
                    'skipped': int(site_row['skipped'] or 0),
                    'unknown': int(site_row['unknown'] or 0),
                })
        return {
            'items': [
                {**dict(row), 'site_summary': site_summary_map.get(row['id'], [])}
                for row in rows
            ],
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()


@router.get('/configs/backup-runs/{run_id}')
def get_backup_run(
    run_id: str,
    site: str = Query(default=''),
    status: str = Query(default='all'),
    search: str = Query(default=''),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    """Return a paged, searchable batch detail without loading every device."""
    conn = get_db_connection()
    try:
        run = conn.execute(
            'SELECT * FROM config_backup_runs WHERE id = ?', (run_id,)
        ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail='Backup run not found')
        site_expr = "COALESCE(NULLIF(TRIM(s.site_name), ''), NULLIF(TRIM(s.site_code), ''), NULLIF(TRIM(d.site), ''), 'Unassigned')"
        site_join = "s.id = d.site_id OR (COALESCE(NULLIF(TRIM(d.site_id), ''), '') = '' AND (s.id = d.site OR s.site_code = d.site OR s.site_name = d.site))"
        where = ['rd.run_id = ?']
        params: list = [run_id]
        requested_site = site.strip()
        if requested_site and requested_site.lower() not in ('all', '*'):
            where.append(f'{site_expr} = ?')
            params.append(requested_site)
        normalized_status = status.strip().lower()
        if normalized_status in ('success', 'failed', 'skipped'):
            where.append('rd.status = ?')
            params.append(normalized_status)
        elif normalized_status == 'unknown':
            where.append("(rd.status IS NULL OR rd.status NOT IN ('success', 'failed', 'skipped'))")
        elif normalized_status in ('abnormal', 'attention'):
            where.append("(rd.status = 'failed' OR rd.status IS NULL OR rd.status NOT IN ('success', 'failed', 'skipped'))")
        if search.strip():
            term = f"%{search.strip()}%"
            where.append('(rd.hostname LIKE ? OR rd.ip_address LIKE ? OR rd.platform LIKE ?)')
            params.extend([term, term, term])
        where_sql = ' AND '.join(where)
        total = conn.execute(
            f'''SELECT COUNT(*) AS c
                FROM config_backup_run_devices rd
                LEFT JOIN devices d ON d.id = rd.device_id
                LEFT JOIN sites s ON {site_join}
                WHERE {where_sql}''',
            tuple(params),
        ).fetchone()['c']
        offset = (page - 1) * page_size
        devices = conn.execute(
            f'''SELECT rd.id, rd.device_id, rd.hostname, rd.ip_address, rd.platform, rd.status,
                      reason, detail, snapshot_id, started_at, finished_at, duration_ms,
                      {site_expr} AS site
               FROM config_backup_run_devices rd
               LEFT JOIN devices d ON d.id = rd.device_id
               LEFT JOIN sites s ON {site_join}
               WHERE {where_sql}
               ORDER BY {site_expr}, rd.hostname, rd.ip_address
               LIMIT ? OFFSET ?''',
            tuple([*params, page_size, offset]),
        ).fetchall()
        site_rows = conn.execute(
            f'''SELECT {site_expr} AS site,
                       COUNT(*) AS total,
                       SUM(CASE WHEN rd.status = 'success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN rd.status = 'failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN rd.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                       SUM(CASE WHEN rd.status IS NULL OR rd.status NOT IN ('success', 'failed', 'skipped') THEN 1 ELSE 0 END) AS unknown
                FROM config_backup_run_devices rd
                LEFT JOIN devices d ON d.id = rd.device_id
                LEFT JOIN sites s ON {site_join}
                WHERE rd.run_id = ?
                GROUP BY {site_expr}
                ORDER BY site''',
            (run_id,),
        ).fetchall()
        run_payload = dict(run)
        run_payload['site_summary'] = [
            {
                'site': row['site'] or 'Unassigned',
                'total': int(row['total'] or 0),
                'success': int(row['success'] or 0),
                'failed': int(row['failed'] or 0),
                'skipped': int(row['skipped'] or 0),
                'unknown': int(row['unknown'] or 0),
            }
            for row in site_rows
        ]
        return {
            'run': run_payload,
            'devices': [dict(row) for row in devices],
            'total': int(total or 0),
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()


@router.post('/configs/snapshots', status_code=201)
def create_snapshot(body: SnapshotCreate):
    """Save a config snapshot to file + DB."""
    ts = _utc_now()
    snap_id = f"snap-{uuid.uuid4().hex[:12]}"
    rel_path = _write_config_file(body.vendor, body.hostname, ts, body.trigger, body.content)
    size = len(body.content.encode('utf-8'))
    metadata = _config_snapshot_metadata(body.content)
    if metadata['integrity_status'] != 'verified':
        _delete_config_file(rel_path)
        raise HTTPException(
            status_code=422,
            detail={
                'message': '配置内容未通过完整性校验，未创建有效版本',
                'reason': metadata['truncation_reason'],
            },
        )

    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO config_snapshots
               (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size,
                raw_hash, normalized_hash, line_count, section_count, integrity_status,
                lifecycle_status, normalizer_version, collected_at, task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (snap_id, body.device_id, body.hostname, body.vendor,
             ts.isoformat(), body.trigger, body.author, body.tag or '',
             rel_path, size, metadata['raw_hash'], metadata['normalized_hash'],
             metadata['line_count'], metadata['section_count'], metadata['integrity_status'],
             metadata['lifecycle_status'], metadata['normalizer_version'], ts.isoformat(), '')
        )
        conn.commit()
    finally:
        conn.close()

    log_audit_event(
        event_type='CONFIG_SNAPSHOT_CREATE',
        category='change_control',
        severity='low',
        status='success',
        summary=f"Created config snapshot for {body.hostname}",
        actor_username=body.author,
        actor_role='Administrator',
        target_type='config_snapshot',
        target_id=snap_id,
        target_name=body.hostname,
        device_id=body.device_id,
        snapshot_id=snap_id,
        details={'trigger': body.trigger, 'vendor': body.vendor, 'size': size, **metadata},
    )

    return {
        'id': snap_id,
        'device_id': body.device_id,
        'hostname': body.hostname,
        'vendor': body.vendor,
        'timestamp': ts.isoformat(),
        'trigger': body.trigger,
        'author': body.author,
        'tag': body.tag,
        'file_path': rel_path,
        'size': size,
        **metadata,
    }


@router.get('/configs/snapshots/{snap_id}/content')
def get_snapshot_content(snap_id: str):
    """Return full config content for a snapshot."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT * FROM config_snapshots WHERE id = ?', (snap_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Snapshot not found')

    content = _read_config_file(row['file_path'])
    actual_metadata = _config_snapshot_metadata(content)
    stored_hash = row['raw_hash'] or ''
    integrity_status = (
        'verified'
        if content and stored_hash and actual_metadata['raw_hash'] == stored_hash
        else 'legacy_unverified'
        if content and not stored_hash
        else 'hash_mismatch'
    )
    return {
        'id': snap_id,
        'content': content,
        'hostname': row['hostname'],
        'vendor': row['vendor'] or '',
        'timestamp': row['timestamp'],
        'trigger': row['trigger'] or '',
        'device_id': row['device_id'],
        'size': row['size'] or 0,
        'raw_hash': stored_hash,
        'normalized_hash': row['normalized_hash'] or '',
        'line_count': row['line_count'] or actual_metadata['line_count'],
        'section_count': row['section_count'] or actual_metadata['section_count'],
        'integrity_status': integrity_status,
        'lifecycle_status': row['lifecycle_status'] or 'stored_raw',
        'normalizer_version': row['normalizer_version'] or '',
    }


@router.get('/configs/snapshots/{snap_id}/download')
def download_snapshot(snap_id: str):
    """Download config snapshot as a .cfg text file."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT * FROM config_snapshots WHERE id = ?', (snap_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Snapshot not found')

    content = _read_config_file(row['file_path'])
    ts_str = row['timestamp'].replace(':', '').replace('-', '').replace('T', '_').split('.')[0]
    filename = f"{row['hostname']}_{ts_str}.cfg"
    return Response(
        content=content,
        media_type='text/plain',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@router.delete('/configs/snapshots/{snap_id}')
def delete_snapshot(snap_id: str):
    """Delete snapshot metadata + file."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT file_path, device_id, hostname FROM config_snapshots WHERE id = ?', (snap_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Snapshot not found')
        _delete_config_file(row['file_path'])
        conn.execute('DELETE FROM config_snapshots WHERE id = ?', (snap_id,))
        conn.commit()
    finally:
        conn.close()
    log_audit_event(
        event_type='CONFIG_SNAPSHOT_DELETE',
        category='change_control',
        severity='medium',
        status='success',
        summary=f"Deleted config snapshot for {row['hostname']}",
        actor_username='admin',
        actor_role='Administrator',
        target_type='config_snapshot',
        target_id=snap_id,
        target_name=row['hostname'],
        device_id=row['device_id'],
        snapshot_id=snap_id,
    )
    return {'ok': True}


# ──────────────────────────────────────────────
# Backup stats & history (for schedule dashboard)
# ──────────────────────────────────────────────

@router.get('/configs/backup-stats')
def get_backup_stats():
    """Return aggregated backup execution statistics for the schedule dashboard."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        # Today's backups
        today_total = conn.execute(
            "SELECT COUNT(*) as c FROM config_snapshots WHERE timestamp >= ?", (today_start,)
        ).fetchone()['c']
        today_scheduled = conn.execute(
            "SELECT COUNT(*) as c FROM config_snapshots WHERE timestamp >= ? AND trigger = 'scheduled'",
            (today_start,)
        ).fetchone()['c']
        today_manual = conn.execute(
            "SELECT COUNT(*) as c FROM config_snapshots WHERE timestamp >= ? AND trigger = 'manual'",
            (today_start,)
        ).fetchone()['c']

        # Prefer the persisted execution ledger when available.  Snapshot
        # rows represent successes only and cannot distinguish a failure from
        # an unplanned device.
        today_run_counts = conn.execute(
            '''SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN rd.status = 'success' THEN 1 ELSE 0 END) AS success_count,
                 SUM(CASE WHEN rd.status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                 SUM(CASE WHEN rd.status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count,
                 SUM(CASE WHEN r.trigger = 'scheduled' THEN 1 ELSE 0 END) AS scheduled_count,
                 SUM(CASE WHEN r.trigger = 'manual' THEN 1 ELSE 0 END) AS manual_count
               FROM config_backup_run_devices rd
               JOIN config_backup_runs r ON r.id = rd.run_id
               WHERE r.started_at >= ?''',
            (today_start,),
        ).fetchone()
        has_today_ledger = int(today_run_counts['total'] or 0) > 0

        # Last 7 days history (grouped by date)
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        daily_rows = conn.execute(
            """SELECT DATE(timestamp) as day, trigger, COUNT(*) as cnt
               FROM config_snapshots WHERE timestamp >= ?
               GROUP BY DATE(timestamp), trigger ORDER BY day""",
            (seven_days_ago,)
        ).fetchall()
        daily_map: dict = {}
        for r in daily_rows:
            d = r['day']
            if d not in daily_map:
                daily_map[d] = {'date': d, 'scheduled': 0, 'manual': 0, 'total': 0}
            daily_map[d][r['trigger']] = daily_map[d].get(r['trigger'], 0) + r['cnt']
            daily_map[d]['total'] += r['cnt']
        daily_history = sorted(daily_map.values(), key=lambda x: x['date'])

        # Devices without a current snapshot are informational until an
        # execution ledger records an actual attempt.
        all_device_ids = conn.execute(
            "SELECT id FROM devices WHERE status = 'online'"
        ).fetchall()
        today_backed_ids = conn.execute(
            "SELECT DISTINCT device_id FROM config_snapshots WHERE timestamp >= ?",
            (today_start,)
        ).fetchall()
        today_backed_set = {r['device_id'] for r in today_backed_ids}
        today_unobserved = sum(1 for r in all_device_ids if r['id'] not in today_backed_set)

        # Total snapshots & total storage
        total_snapshots = conn.execute("SELECT COUNT(*) as c FROM config_snapshots").fetchone()['c']
        total_devices_backed = conn.execute(
            "SELECT COUNT(DISTINCT device_id) as c FROM config_snapshots"
        ).fetchone()['c']
        storage_row = conn.execute("SELECT COALESCE(SUM(size), 0) as s FROM config_snapshots").fetchone()
        storage_bytes = storage_row['s'] if storage_row else 0

        # Per-device latest backup & count.
        # Original code did 2 SQL queries per device (count+max, then last
        # trigger) inside a Python loop, scaling linearly with device count.
        # Replaced with two grouped queries — independent of device count.
        devices = conn.execute(
            "SELECT id, hostname, ip_address, platform, status FROM devices"
        ).fetchall()

        agg_rows = conn.execute(
            """SELECT device_id, COUNT(*) AS cnt, MAX(timestamp) AS latest
               FROM config_snapshots
               GROUP BY device_id"""
        ).fetchall()
        agg_map = {r['device_id']: {'cnt': r['cnt'], 'latest': r['latest']} for r in agg_rows}

        # Last trigger per device. We compute MAX(timestamp) per device, then
        # join back to find that row's `trigger`. Works in both PG and SQLite.
        last_trigger_rows = conn.execute(
            """SELECT cs.device_id, cs.trigger
               FROM config_snapshots cs
               INNER JOIN (
                   SELECT device_id, MAX(timestamp) AS max_ts
                   FROM config_snapshots GROUP BY device_id
               ) m ON m.device_id = cs.device_id AND m.max_ts = cs.timestamp"""
        ).fetchall()
        last_trigger_map: dict = {}
        for r in last_trigger_rows:
            # In the unlikely case of duplicate max_ts within a device, last
            # write wins — matches the previous LIMIT 1 behaviour.
            last_trigger_map[r['device_id']] = r['trigger']

        device_stats = []
        for dev in devices:
            agg = agg_map.get(dev['id'], {'cnt': 0, 'latest': None})
            device_stats.append({
                'id': dev['id'],
                'hostname': dev['hostname'],
                'ip_address': dev['ip_address'],
                'platform': dev['platform'],
                'status': dev['status'],
                'backup_count': agg['cnt'] or 0,
                'latest_backup': agg['latest'],
                'last_trigger': last_trigger_map.get(dev['id']),
            })

        # Recent 20 backups (execution log)
        recent = conn.execute(
            """SELECT id, device_id, hostname, vendor, timestamp, trigger, author, tag, size
               FROM config_snapshots ORDER BY timestamp DESC LIMIT 20"""
        ).fetchall()
        recent_list = [dict(r) for r in recent]

        return {
            'success': True,
            'data': {
                'today': {
                    'total': int(today_run_counts['total'] or today_total) if has_today_ledger else today_total,
                    'scheduled': int(today_run_counts['scheduled_count'] or 0) if has_today_ledger else today_scheduled,
                    'manual': int(today_run_counts['manual_count'] or 0) if has_today_ledger else today_manual,
                    'success': int(today_run_counts['success_count'] or 0) if has_today_ledger else today_total,
                    'failed': int(today_run_counts['failed_count'] or 0) if has_today_ledger else 0,
                    'skipped': int(today_run_counts['skipped_count'] or 0) if has_today_ledger else 0,
                    'unobserved': 0 if has_today_ledger else today_unobserved,
                },
                'daily_history': daily_history,
                'total_snapshots': total_snapshots,
                'total_devices_backed': total_devices_backed,
                'storage_bytes': storage_bytes,
                'device_stats': device_stats,
                'recent_backups': recent_list,
            }
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Global config search across ALL snapshots
# ──────────────────────────────────────────────

@router.get('/configs/search')
def search_configs(q: str = '', limit: int = 50):
    """
    Search latest config snapshots for a keyword.
    Caps file I/O to avoid excessive reads on large deployments.
    """
    if not q or len(q.strip()) < 2:
        return []

    query = q.strip().lower()
    MAX_FILE_READS = 200  # Cap to avoid excessive disk I/O

    conn = get_db_connection()
    try:
        all_devices = conn.execute(
            'SELECT id, hostname, ip_address, platform FROM devices'
        ).fetchall()

        latest_snaps = conn.execute('''
            SELECT cs.* FROM config_snapshots cs
            INNER JOIN (
                SELECT device_id, MAX(timestamp) AS max_ts
                FROM config_snapshots
                GROUP BY device_id
            ) latest ON cs.device_id = latest.device_id AND cs.timestamp = latest.max_ts
            ORDER BY cs.timestamp DESC
        ''').fetchall()
    finally:
        conn.close()

    device_map = {d['id']: dict(d) for d in all_devices}

    results = []
    files_read = 0
    for snap in latest_snaps:
        if files_read >= MAX_FILE_READS or len(results) >= limit:
            break
        snap = dict(snap)
        if not snap.get('file_path'):
            continue

        files_read += 1
        content = _read_config_file(snap['file_path'])
        if not content:
            continue

        lines = content.split('\n')
        matches = []
        for i, line in enumerate(lines):
            if query in line.lower():
                ctx_start = max(0, i - 1)
                ctx_end = min(len(lines), i + 2)
                matches.append({
                    'line': i + 1,
                    'content': line,
                    'context': [{'line': ctx_start + j + 1, 'content': lines[ctx_start + j]} for j in range(ctx_end - ctx_start)],
                })
        if not matches:
            continue

        dev = device_map.get(snap['device_id'], {})
        results.append({
            'device_id': snap['device_id'],
            'hostname': snap.get('hostname') or dev.get('hostname', ''),
            'ip_address': dev.get('ip_address', ''),
            'platform': dev.get('platform', ''),
            'vendor': snap.get('vendor', ''),
            'snapshot_id': snap['id'],
            'snapshot_time': snap.get('timestamp', ''),
            'total_matches': len(matches),
            'matches': matches[:30],
        })

    results.sort(key=lambda x: x['total_matches'], reverse=True)
    return results[:limit]


# ──────────────────────────────────────────────
# Scheduled backup settings (stored in global_vars)
# ──────────────────────────────────────────────

SCHEDULE_KEY = 'backup_schedule'
DEFAULT_SCHEDULE = {'enabled': True, 'cron': '0 2 * * *'}


def _get_schedule_from_db() -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT value FROM global_vars WHERE key = ?", (SCHEDULE_KEY,)
        ).fetchone()
        if row:
            return json.loads(row['value'])
        return DEFAULT_SCHEDULE.copy()
    finally:
        conn.close()


def _save_schedule_to_db(cfg: dict):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO global_vars (id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(uuid.uuid4()), SCHEDULE_KEY, json.dumps(cfg))
        )
        conn.commit()
    finally:
        conn.close()


@router.get('/configs/schedule')
def get_schedule():
    cfg = _get_schedule_from_db()
    # 兼容旧格式：如果库里没有 cron 字段，从 hour/minute 合成
    if 'cron' not in cfg:
        h = cfg.get('hour', 2)
        m = cfg.get('minute', 0)
        cfg['cron'] = f'{m} {h} * * *'
    return cfg


@router.put('/configs/schedule')
def update_schedule(body: ScheduleUpdate):
    cron_expr = body.cron.strip()
    # 验证 cron 表达式合法性
    try:
        from croniter import croniter
        if not croniter.is_valid(cron_expr):
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {cron_expr}")
    cfg = {'enabled': body.enabled, 'cron': cron_expr}
    _save_schedule_to_db(cfg)
    reschedule_backup(cfg)
    return cfg


# ── In-memory progress registry ──────────────────────────────────────────────
# Keyed by run_id (uuid hex). Entries are cleaned up after 10 minutes.
# Shape: { run_id: { total, done, success, failed, skipped, devices: [...], finished_at } }
_backup_runs: dict[str, dict] = {}

# How many devices to back up in parallel. SSH connections are I/O-bound so
# Keep the batch conservative; the shared SSH limiter remains the final guard.
# Increase via BACKUP_CONCURRENCY env var if your network can handle more.
# Recommended range: 5–50. Higher values may trigger SSH rate-limiting on devices.
import os as _os
BACKUP_CONCURRENCY = int(_os.environ.get('BACKUP_CONCURRENCY', '10'))


@router.post('/configs/run-now')
async def trigger_backup_now():
    """Trigger the same backup routine used by the scheduler, on demand.

    Returns a ``run_id`` that the frontend can poll via
    ``GET /configs/run-now/{run_id}/progress`` to show a live progress bar.
    """
    import asyncio
    run_id = uuid.uuid4().hex
    asyncio.create_task(run_scheduled_backup(run_id=run_id))
    return {
        'status': 'started',
        'run_id': run_id,
        'message': 'Config backup triggered. Poll /configs/run-now/{run_id}/progress for status.',
    }


@router.get('/configs/run-now/{run_id}/progress')
def get_backup_progress(run_id: str):
    """Return live progress for a manual backup run."""
    entry = _backup_runs.get(run_id)
    if not entry:
        raise HTTPException(status_code=404, detail='Run not found or already expired')
    return entry


@router.get('/configs/schedule/preview')
def preview_schedule(n: int = Query(default=10, ge=1, le=50)):
    """Return the next N scheduled execution times + device list."""
    from croniter import croniter
    cfg = _get_schedule_from_db()
    cron_expr = cfg.get('cron', '0 2 * * *')
    if 'cron' not in cfg:
        h = cfg.get('hour', 2)
        m = cfg.get('minute', 0)
        cron_expr = f'{m} {h} * * *'
    enabled = cfg.get('enabled', True)

    # 计算未来 N 次执行时间
    upcoming: list[str] = []
    if enabled:
        cron = croniter(cron_expr, datetime.now(timezone.utc))
        for _ in range(n):
            upcoming.append(cron.get_next(datetime).isoformat())

    # 备份涉及的设备列表
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, hostname, ip_address, platform, status FROM devices WHERE status = 'online'"
        ).fetchall()
        devices = [dict(r) for r in rows]
    finally:
        conn.close()

    MOCK_IPS_SET = {'127.0.0.1', '0.0.0.0', 'localhost'}
    devices = [d for d in devices if (d.get('ip_address') or '') not in MOCK_IPS_SET]

    return {
        'enabled': enabled,
        'cron': cron_expr,
        'upcoming': upcoming,
        'devices': devices,
        'device_count': len(devices),
    }


# ──────────────────────────────────────────────
# Backup retention policy
# ──────────────────────────────────────────────

RETENTION_KEY = 'backup_retention'
DEFAULT_RETENTION = {'max_days': 90, 'max_per_device': 30}


class RetentionUpdate(BaseModel):
    max_days: int = Field(default=90, ge=1, le=3650)
    max_per_device: int = Field(default=30, ge=1, le=5000)


def _get_retention_from_db() -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT value FROM global_vars WHERE key = ?", (RETENTION_KEY,)
        ).fetchone()
        if row:
            raw = json.loads(row['value'])
            return {
                'max_days': min(3650, max(1, int(raw.get('max_days', DEFAULT_RETENTION['max_days'])))),
                'max_per_device': min(5000, max(1, int(raw.get('max_per_device', DEFAULT_RETENTION['max_per_device'])))),
            }
        return DEFAULT_RETENTION.copy()
    finally:
        conn.close()


def _save_retention_to_db(cfg: dict):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO global_vars (id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(uuid.uuid4()), RETENTION_KEY, json.dumps(cfg))
        )
        conn.commit()
    finally:
        conn.close()


@router.get('/configs/retention')
def get_retention():
    return _get_retention_from_db()


@router.put('/configs/retention')
def update_retention(body: RetentionUpdate):
    cfg = {'max_days': body.max_days, 'max_per_device': body.max_per_device}
    _save_retention_to_db(cfg)
    return cfg


def _cleanup_expired_snapshots(
    *,
    policy_id: str = '',
    max_days: int | None = None,
    max_per_device: int | None = None,
):
    """Delete snapshots that exceed retention policy (by age and per-device count)."""
    if max_days is None or max_per_device is None:
        retention = _get_retention_from_db()
        max_days = max_days or retention.get('max_days', 90)
        max_per_device = max_per_device or retention.get('max_per_device', 30)
    max_days = max(1, int(max_days))
    max_per_device = max(1, int(max_per_device))
    deleted = 0
    policy_clause = ' AND policy_id = ?' if policy_id else ''

    conn = get_db_connection()
    try:
        # 1. Delete snapshots older than max_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_days)).replace(microsecond=0).isoformat()
        old = conn.execute(
            f'SELECT id, file_path FROM config_snapshots WHERE timestamp < ?{policy_clause}',
            (cutoff, policy_id) if policy_id else (cutoff,),
        ).fetchall()
        for s in old:
            _delete_config_file(s['file_path'])
        if old:
            conn.execute(
                f'DELETE FROM config_snapshots WHERE timestamp < ?{policy_clause}',
                (cutoff, policy_id) if policy_id else (cutoff,),
            )
            deleted += len(old)

        # 2. Per-device: keep only max_per_device most recent
        devs = conn.execute(
            f'SELECT DISTINCT device_id FROM config_snapshots WHERE 1 = 1{policy_clause}',
            (policy_id,) if policy_id else (),
        ).fetchall()
        for d in devs:
            excess = conn.execute(
                f'''SELECT id, file_path FROM config_snapshots
                    WHERE device_id = ?{policy_clause}
                    ORDER BY timestamp DESC LIMIT 1000 OFFSET ?''',
                (
                    (d['device_id'], policy_id, max_per_device)
                    if policy_id
                    else (d['device_id'], max_per_device)
                ),
            ).fetchall()
            for s in excess:
                _delete_config_file(s['file_path'])
            if excess:
                ids = [s['id'] for s in excess]
                conn.execute(
                    f"DELETE FROM config_snapshots WHERE id IN ({','.join('?' * len(ids))})",
                    ids
                )
                deleted += len(excess)

        conn.commit()
    finally:
        conn.close()

    if deleted:
        logger.info(
            "[Retention Cleanup] Removed %d expired snapshots for policy=%s",
            deleted,
            policy_id or 'legacy-global',
        )


def reschedule_backup_policies():
    """Replace all policy-backed backup jobs with the current database state."""
    for job in scheduler.get_jobs():
        if job.id == 'daily_backup' or job.id.startswith('config_backup_policy:'):
            scheduler.remove_job(job.id)

    conn = get_db_connection()
    try:
        policies = config_backup_policy_service.list_enabled_policies(conn)
    finally:
        conn.close()

    for policy in policies:
        try:
            trigger = CronTrigger.from_crontab(
                policy['cron_expr'],
                timezone=policy.get('timezone') or 'Asia/Shanghai',
            )
            scheduler.add_job(
                run_scheduled_backup,
                trigger,
                kwargs={'policy_id': policy['id']},
                id=f"config_backup_policy:{policy['id']}",
                name=f"Config Backup · {policy['name']}",
                replace_existing=True,
            )
        except Exception:
            logger.exception(
                "[Scheduler] Could not register config backup policy %s",
                policy.get('id'),
            )


def reschedule_backup(cfg: dict):
    """Compatibility bridge from the legacy global schedule to the default policy."""
    cron_expr = str(cfg.get('cron') or '').strip()
    if not cron_expr:
        cron_expr = f"{cfg.get('minute', 0)} {cfg.get('hour', 2)} * * *"
    conn = get_db_connection()
    try:
        config_backup_policy_service.sync_default_policy_from_legacy(
            conn,
            enabled=bool(cfg.get('enabled', True)),
            cron_expr=cron_expr,
        )
    finally:
        conn.close()
    reschedule_backup_policies()


# ──────────────────────────────────────────────
# Core backup logic - called by scheduler & manual triggers
# ──────────────────────────────────────────────

MOCK_IPS = {'127.0.0.1', '0.0.0.0', 'localhost'}


async def run_scheduled_backup(
    run_id: str | None = None,
    policy_id: str | None = None,
    author: str | None = None,
):
    """Back up online devices matched by a saved policy.

    Concurrency:
      - Up to the policy concurrency limit (default 10) devices are backed up in
        parallel using asyncio.Semaphore + run_in_executor.
      - Each device gets its own AutomationService instance so there is no
        shared state between concurrent workers.

    Progress tracking:
      - When ``run_id`` is provided the function writes live progress into
        ``_backup_runs[run_id]`` so the frontend can poll it.
    """
    import asyncio
    from services.automation_service import AutomationService
    from core.crypto import decrypt_credential
    from api.devices import _record_instant_execution
    import time as _time

    persisted_run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    run_trigger = 'manual' if run_id else 'scheduled'
    run_author = author or ('admin' if run_id else 'system')
    start_time = _time.time()
    conn = get_db_connection()
    try:
        policy = (
            config_backup_policy_service.get_policy(conn, policy_id, include_secret=True)
            if policy_id
            else None
        )
        if policy_id and not policy:
            logger.error("[Scheduled Backup] Policy %s no longer exists", policy_id)
            return
        device_rows = conn.execute(
            "SELECT id, asset_id, hostname, ip_address, platform, vendor, role, site, site_id, status, "
            "platform_profile_id, "
            "config_backup_enabled, username, password, "
            "normal_username, normal_password, admin_username, admin_password, enable_password, "
            "credential_id, admin_credential_id, credential_source, vault_path, management_port "
            "FROM devices WHERE status = 'online'"
        ).fetchall()
        devices = (
            config_backup_policy_service.filter_devices_by_scope(
                conn,
                device_rows,
                policy.get('scope'),
            )
            if policy
            else [dict(row) for row in device_rows]
        )
    finally:
        conn.close()

    run_concurrency = int((policy or {}).get('concurrency') or BACKUP_CONCURRENCY)
    run_retry_count = int((policy or {}).get('retry_count') or 0)
    # Existing policies may still persist the historical 20/30 second value.
    # The effective SSH budget must cover every transport stage, so keep it at
    # a minimum of 60 seconds until the policy is explicitly updated.
    run_timeout_seconds = max(60, int((policy or {}).get('timeout_seconds') or 60))
    ssh_timeout_options = {
        'conn_timeout': run_timeout_seconds,
        'timeout': run_timeout_seconds,
        'banner_timeout': run_timeout_seconds,
        'auth_timeout': run_timeout_seconds,
        'blocking_timeout': run_timeout_seconds,
        'session_timeout': max(120, run_timeout_seconds),
        'read_timeout': run_timeout_seconds,
        'command_read_timeout': run_timeout_seconds,
    }
    change_only = bool((policy or {}).get('change_only', False))
    logger.info(
        "[Scheduled Backup] Starting policy=%s targets=%d concurrency=%d",
        policy_id or 'legacy-all',
        len(devices),
        run_concurrency,
    )

    # Platforms we back up (anything producing a textual running-config).
    NETWORK_PLATFORM_KEYWORDS = (
        'cisco', 'arista', 'rgos', 'ruijie',
        'juniper', 'junos',
        'huawei', 'vrp',
        'h3c', 'comware',
        'zte', 'zxros',
        'maipu',
        'raisecom',
        'dptech',
        'fortinet',
        'hillstone',
        'sonic',
        'centec',
    )

    def _is_network_device(platform: str) -> bool:
        p = (platform or '').lower()
        return any(kw in p for kw in NETWORK_PLATFORM_KEYWORDS)

    # Filter to eligible devices upfront so progress totals are accurate
    eligible = []
    skipped_count = 0
    for device in devices:
        if (device['ip_address'] or '') in MOCK_IPS:
            skipped_count += 1
            logger.info(f"[Scheduled Backup] [SKIP] {device['hostname']} (mock IP, skipped)")
            continue
        if not _is_network_device(device['platform']):
            skipped_count += 1
            logger.info(f"[Scheduled Backup] [SKIP] {device['hostname']} (platform={device['platform']} is not a network device, skipped)")
            continue
        eligible.append(device)

    total = len(eligible)
    run_device_rows: dict[str, str] = {}
    try:
        run_device_rows = _create_backup_run(
            persisted_run_id,
            trigger=run_trigger,
            author=run_author,
            devices=devices,
            eligible_ids={str(device['id']) for device in eligible},
            policy_id=policy_id or '',
            policy_snapshot=json.dumps({
                'policy_id': policy_id or '',
                'policy_name': (policy or {}).get('name', 'Legacy all devices'),
                'scope': (policy or {}).get('scope', {}),
                'cron_expr': (policy or {}).get('cron_expr', ''),
                'timezone': (policy or {}).get('timezone', ''),
                'change_only': change_only,
                'concurrency': run_concurrency,
                'retry_count': run_retry_count,
                'timeout_seconds': run_timeout_seconds,
                'platform_scope': 'network_devices',
            }, ensure_ascii=False),
        )
    except Exception:
        logger.exception("[Scheduled Backup] Could not persist backup run %s", persisted_run_id)

    # Initialise progress entry
    if run_id:
        _backup_runs[run_id] = {
            'run_id': run_id,
            'total': total,
            'skipped': skipped_count,
            'done': 0,
            'success': 0,
            'failed': 0,
            'finished': False,
            'finished_at': None,
            'devices': [],
            'started_at': _time.time(),
        }

    success_count = 0
    failed_count = 0
    created_backup_items: list[dict] = []
    sem = asyncio.Semaphore(run_concurrency)

    collect_startup_config = bool((policy or {}).get('collect_startup_config')) or (
        'startup' in (policy or {}).get('config_types', [])
    )

    def _looks_like_error(raw: str) -> bool:
        if not raw or not raw.strip():
            return True
        low = raw.lower()
        markers = (
            '[mock ',
            '% invalid input',
            '% permission denied',
            '% authorization failed',
            'bash: ',
            'command not found',
        )
        return any(m in low for m in markers)

    async def _backup_one(device) -> dict:
        """Back up a single device (running-config and optionally startup-config); returns a result dict."""
        nonlocal success_count, failed_count, created_backup_items

        from core.platform_utils import normalize_device_platform
        _platform = normalize_device_platform(device.get('vendor'), device.get('platform'))
        if any(k in _platform for k in ('cisco', 'arista', 'rgos', 'ruijie', 'zte', 'zxros', 'maipu', 'raisecom', 'sonic', 'centec')):
            _running_cmd = 'show running-config'
            _startup_cmd = 'show startup-config'
        elif 'juniper' in _platform or 'junos' in _platform:
            _running_cmd = 'show configuration'
            _startup_cmd = 'show configuration'
        elif 'fortinet' in _platform:
            _running_cmd = 'show full-configuration'
            _startup_cmd = 'show full-configuration'
        else:
            _running_cmd = 'display current-configuration'
            _startup_cmd = 'display saved-configuration'

        d = dict(device)
        d['platform'] = _platform
        d.update(ssh_timeout_options)
        from services.vault_service import resolve_device_credentials
        creds = resolve_device_credentials(d)
        username = creds.get('admin_username') or creds.get('username') or ''
        password = creds.get('admin_password') or creds.get('password') or ''
        enable_pass = creds.get('enable_password') or ''

        if not username or not password:
            failed_count += 1
            logger.error(f"[Scheduled Backup] [X] {device['hostname']}: no usable credentials")
            return {
                'hostname': device['hostname'],
                'status': 'failed',
                'reason': '缺失凭证',
                'detail': '未配置可用凭证，请在资产中绑定登录账号。'
            }

        d['username'] = username
        d['password'] = password
        d['enable_password'] = enable_pass
        cred_kind = 'resolved'

        output = ''
        startup_output = ''
        backup_ok = False
        results = None

        async with sem:
            for attempt in range(run_retry_count + 1):
                try:
                    commands = [_running_cmd, _startup_cmd] if collect_startup_config else [_running_cmd]
                    if d.get('platform_profile_id'):
                        from services.platform_registry_service import execute_platform_action
                        registry_result = await asyncio.to_thread(
                            execute_platform_action,
                            str(d['id']),
                            'get_running_config',
                            user={
                                'id': f"config-backup:{d['id']}",
                                'username': 'config-backup',
                                'role': 'Administrator',
                                'tenant_id': d.get('tenant_id') or '',
                            },
                            connection_options=ssh_timeout_options,
                            include_raw_output=True,
                        )
                        output = str(registry_result.get('raw_output') or '')
                        results = [{
                            'success': bool(registry_result.get('success')),
                            'output': output,
                            'error': registry_result.get('error') or registry_result.get('error_code'),
                        }]
                        if collect_startup_config and results[0].get('success'):
                            st_reg_result = await asyncio.to_thread(
                                execute_platform_action,
                                str(d['id']),
                                'get_startup_config',
                                user={
                                    'id': f"config-backup:{d['id']}",
                                    'username': 'config-backup',
                                    'role': 'Administrator',
                                    'tenant_id': d.get('tenant_id') or '',
                                },
                                connection_options=ssh_timeout_options,
                                include_raw_output=True,
                            )
                            st_raw = str(st_reg_result.get('raw_output') or '')
                            results.append({
                                'success': bool(st_reg_result.get('success')),
                                'output': st_raw,
                                'error': st_reg_result.get('error') or st_reg_result.get('error_code'),
                            })
                    else:
                        driver_type = 'mock' if d.get('ip_address') in ['127.0.0.1', '0.0.0.0'] else 'netmiko'
                        service = AutomationService(driver_type=driver_type)
                        results = await asyncio.get_event_loop().run_in_executor(
                            service.orchestrator.executor,
                            lambda: service.execute_commands(d, commands, is_config=False)
                        )

                    if results and results[0].get('success', False):
                        output = results[0].get('output') or results[0].get('stdout') or ''
                        if collect_startup_config and len(results) > 1 and results[1].get('success', False):
                            startup_output = results[1].get('output') or results[1].get('stdout') or ''
                        if not _looks_like_error(output) and not output.startswith('% '):
                            _record_instant_execution(
                                d['id'],
                                f"Config Backup · {(policy or {}).get('name', 'Manual')}",
                                commands,
                                'completed',
                                platform=d.get('platform'),
                                output=output,
                                device_info=d,
                            )
                            break
                    err = (
                        results[0].get('error')
                        or results[0].get('stderr')
                        or 'Unknown error'
                    ) if results else 'Unknown error'
                    logger.warning(
                        "[Scheduled Backup] Attempt %d/%d failed for %s (%s): %s",
                        attempt + 1,
                        run_retry_count + 1,
                        device['hostname'],
                        cred_kind,
                        err,
                    )
                    output = ''
                    startup_output = ''
                except Exception as e:
                    logger.warning(
                        "[Scheduled Backup] Attempt %d/%d raised for %s: %s",
                        attempt + 1,
                        run_retry_count + 1,
                        device['hostname'],
                        e,
                    )
                    output = ''
                    startup_output = ''

        if not _looks_like_error(output) and not output.startswith('% '):
            backup_ok = True

        if not backup_ok:
            failed_count += 1
            logger.error(
                f"[Scheduled Backup] [X] {device['hostname']} ({cred_kind}): "
                f"no valid config obtained (output length={len(output)})"
            )
            
            err_str = 'Unknown error'
            if results and results[0]:
                err_str = results[0].get('error') or results[0].get('stderr') or 'No config output'
            elif results is None:
                err_str = 'No connection could be established'

            from drivers.ssh_compat import diagnose_ssh_failure
            from services.connection_profile import resolve_ssh_port
            dev_port = resolve_ssh_port(d)
            short_reason, detail_reason = diagnose_ssh_failure(str(err_str), device.get('ip_address', ''), port=dev_port)

            return {
                'hostname': device['hostname'],
                'status': 'failed',
                'reason': short_reason,
                'detail': detail_reason
            }

        try:
            metadata = _config_snapshot_metadata(output)
            if metadata['integrity_status'] != 'verified':
                failed_count += 1
                detail_map = {
                    'empty_output': '设备返回内容为空',
                    'command_error_output': '执行配置命令报错（权限不足或命令不支持）',
                    'suspiciously_short': '配置输出行数过少，未通过完整性校验',
                }
                detail_msg = detail_map.get(metadata.get('truncation_reason', ''), '配置内容未通过完整性校验')
                return {
                    'hostname': device['hostname'],
                    'status': 'failed',
                    'reason': '完整性校验失败',
                    'detail': detail_msg,
                }
            if change_only:
                conn_latest = get_db_connection()
                try:
                    latest = conn_latest.execute(
                        """
                        SELECT id, normalized_hash
                        FROM config_snapshots
                        WHERE device_id = ? AND config_type = 'running'
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """,
                        (device['id'],),
                    ).fetchone()
                finally:
                    conn_latest.close()
                if latest and latest['normalized_hash'] == metadata['normalized_hash']:
                    success_count += 1
                    return {
                        'hostname': device['hostname'],
                        'status': 'success',
                        'reason': '配置未变化',
                        'detail': '标准化配置与最近版本一致，按策略未重复归档。',
                        'snapshot_id': latest['id'],
                        'unchanged': True,
                    }

            platform = _platform.lower()
            if 'cisco' in platform:
                vendor = 'Cisco'
            elif 'juniper' in platform or 'junos' in platform:
                vendor = 'Juniper'
            elif 'huawei' in platform:
                vendor = 'Huawei'
            elif 'h3c' in platform or 'comware' in platform:
                vendor = 'H3C'
            elif 'arista' in platform or 'eos' in platform:
                vendor = 'Arista'
            elif 'ruijie' in platform or 'rgos' in platform:
                vendor = 'Ruijie'
            else:
                vendor = str(device.get('vendor') or 'Other')

            ts = _utc_now()
            rel_path = _write_config_file(vendor, device['hostname'], ts, run_trigger, output, config_type='running')
            size = len(output.encode('utf-8'))
            snap_id = f"snap-{uuid.uuid4().hex[:12]}"
            
            created_backup_items.append({
                'local_path': os.path.join(BACKUP_ROOT, rel_path.replace('/', os.sep).replace('\\', os.sep)),
                'remote_name': os.path.basename(rel_path),
                'archive_name': rel_path,
                'hostname': device['hostname'],
                # Keep local snapshots encrypted, but publish readable config
                # text when the completed snapshot is offloaded remotely.
                'data': output.encode('utf-8'),
            })

            # Optional Startup Config collection & Unsaved Drift Detection
            has_unsaved = 0
            unsaved_summary = ''
            startup_snap_id = None
            if collect_startup_config and startup_output and not _looks_like_error(startup_output) and not startup_output.startswith('% '):
                try:
                    st_metadata = _config_snapshot_metadata(startup_output)
                    if st_metadata['integrity_status'] == 'verified':
                        if metadata['normalized_hash'] != st_metadata['normalized_hash']:
                            has_unsaved = 1
                            unsaved_summary = f"未保存运行配置差异 (运行 {metadata['line_count']} 行 vs 启动 {st_metadata['line_count']} 行)"
                        else:
                            has_unsaved = 0
                            unsaved_summary = "运行配置与启动配置一致"

                        st_rel_path = _write_config_file(vendor, device['hostname'], ts, run_trigger, startup_output, config_type='startup')
                        startup_snap_id = f"snap-{uuid.uuid4().hex[:12]}"
                        st_size = len(startup_output.encode('utf-8'))

                        conn_st = get_db_connection()
                        try:
                            conn_st.execute(
                                '''INSERT INTO config_snapshots
                                   (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size,
                                    raw_hash, normalized_hash, line_count, section_count, integrity_status,
                                    lifecycle_status, normalizer_version, collected_at, task_id, policy_id, config_type,
                                    has_unsaved_changes, unsaved_diff_summary)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                (startup_snap_id, device['id'], device['hostname'], vendor,
                                 ts.isoformat(), run_trigger, run_author, '', st_rel_path, st_size,
                                 st_metadata['raw_hash'], st_metadata['normalized_hash'], st_metadata['line_count'],
                                 st_metadata['section_count'], st_metadata['integrity_status'],
                                 st_metadata['lifecycle_status'], st_metadata['normalizer_version'],
                                 ts.isoformat(), persisted_run_id, policy_id or '', 'startup',
                                 has_unsaved, unsaved_summary)
                            )
                            conn_st.commit()
                        finally:
                            conn_st.close()

                        created_backup_items.append({
                            'local_path': os.path.join(BACKUP_ROOT, st_rel_path.replace('/', os.sep).replace('\\', os.sep)),
                            'remote_name': os.path.basename(st_rel_path),
                            'archive_name': st_rel_path,
                            'hostname': device['hostname'],
                            'data': startup_output.encode('utf-8'),
                        })
                except Exception as st_err:
                    logger.warning(f"[Scheduled Backup] Startup config process error for {device['hostname']}: {st_err}")

            conn2 = get_db_connection()
            try:
                conn2.execute(
                    '''INSERT INTO config_snapshots
                       (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size,
                        raw_hash, normalized_hash, line_count, section_count, integrity_status,
                        lifecycle_status, normalizer_version, collected_at, task_id, policy_id, config_type,
                        has_unsaved_changes, unsaved_diff_summary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (snap_id, device['id'], device['hostname'], vendor,
                     ts.isoformat(), run_trigger, run_author, '', rel_path, size,
                     metadata['raw_hash'], metadata['normalized_hash'], metadata['line_count'],
                     metadata['section_count'], metadata['integrity_status'],
                     metadata['lifecycle_status'], metadata['normalizer_version'],
                     ts.isoformat(), persisted_run_id, policy_id or '', 'running',
                     has_unsaved, unsaved_summary)
                )
                conn2.commit()
            finally:
                conn2.close()
            success_count += 1
            logger.info(f"[Scheduled Backup] [OK] {device['hostname']}")
            return {
                'hostname': device['hostname'],
                'status': 'success',
                'size': size,
                'snapshot_id': snap_id,
                'startup_snapshot_id': startup_snap_id,
                'has_unsaved_changes': bool(has_unsaved),
                'unsaved_diff_summary': unsaved_summary,
                'raw_hash': metadata['raw_hash'],
                'normalized_hash': metadata['normalized_hash'],
                'integrity_status': metadata['integrity_status'],
            }
        except Exception as e:
            failed_count += 1
            logger.error(f"[Scheduled Backup] [X] {device['hostname']}: {e}")
            return {
                'hostname': device['hostname'],
                'status': 'failed',
                'reason': '系统异常',
                'detail': str(e)
            }

    # Run all eligible devices concurrently (bounded by semaphore)
    async def _run_with_progress(device):
        device_started = _time.perf_counter()
        result = await _backup_one(device)
        device_finished = _utc_now_iso()
        row_id = run_device_rows.get(str(device['id']))
        if row_id:
            _record_backup_run_device(
                row_id,
                result=result,
                finished_at=device_finished,
                duration_ms=round((_time.perf_counter() - device_started) * 1000),
            )
        if run_id and run_id in _backup_runs:
            entry = _backup_runs[run_id]
            entry['done'] += 1
            entry['success'] = success_count
            entry['failed'] = failed_count
            entry['devices'].append(result)
        return result

    await asyncio.gather(*[_run_with_progress(dev) for dev in eligible])

    # Remote file archive offloading.  Configuration collection above remains
    # SSH/CLI based; this step only copies completed local snapshots.
    tftp_enabled = bool((policy or {}).get('tftp_enabled'))
    tftp_server = str((policy or {}).get('tftp_server') or '').strip()
    tftp_port = int((policy or {}).get('tftp_port') or 69)
    tftp_path_prefix = str((policy or {}).get('tftp_path_prefix') or 'backups').strip()
    tftp_protocol = str((policy or {}).get('tftp_protocol') or 'tftp').strip().lower()
    tftp_username = str((policy or {}).get('tftp_username') or '').strip()
    tftp_password = str((policy or {}).get('tftp_password') or '')

    tftp_status = 'none'
    tftp_log = ''
    tftp_uploaded_count = 0

    if tftp_enabled and tftp_server:
        try:
            from services.file_transfer_service import batch_upload_configs
            remote_archive_name = _config_archive_name(persisted_run_id)
            summary_text = (
                f"Nexora Config Backup Batch Summary\n"
                f"Run ID: {persisted_run_id}\n"
                f"Policy: {(policy or {}).get('name', 'Manual/Legacy')}\n"
                f"Finished At: {_utc_now_iso()}\n"
                f"Total Devices: {len(devices)}, Success: {success_count}, Failed: {failed_count}, Skipped: {skipped_count}\n"
                f"Archive File: {remote_archive_name}\n"
                f"Files In Archive: {len(created_backup_items)}\n"
            )
            tftp_res = await asyncio.to_thread(
                batch_upload_configs,
                protocol=tftp_protocol,
                server_ip=tftp_server,
                items=created_backup_items,
                server_port=tftp_port,
                username=tftp_username,
                password=tftp_password,
                path_prefix=tftp_path_prefix,
                summary_log=summary_text,
                archive_name=remote_archive_name,
            )
            tftp_status = tftp_res.get('status', 'failed')
            tftp_uploaded_count = (
                tftp_res.get('file_count', 0)
                if tftp_status in ('success', 'partial')
                else 0
            )
            tftp_log = "\n".join(tftp_res.get('details', []))
            logger.info(
                f"[Scheduled Backup] {tftp_protocol.upper()} archive offload completed "
                f"with status={tftp_status} (archives={tftp_res.get('uploaded', 0)}, files={tftp_res.get('file_count', 0)})"
            )
        except Exception as tftp_exc:
            tftp_status = 'failed'
            tftp_log = f"{tftp_protocol.upper()} archive upload exception: {tftp_exc}"
            logger.error(f"[Scheduled Backup] {tftp_protocol.upper()} archive offload error: {tftp_exc}")

    try:
        _finish_backup_run(
            persisted_run_id,
            tftp_status=tftp_status,
            tftp_server=tftp_server,
            tftp_log=tftp_log,
            tftp_uploaded_count=tftp_uploaded_count,
        )
    except Exception:
        logger.exception("[Scheduled Backup] Could not finalize backup run %s", persisted_run_id)

    duration = round(_time.time() - start_time, 2)
    logger.info(
        f"[Scheduled Backup] Done - {success_count} succeeded, {failed_count} failed, {skipped_count} skipped. "
        f"Concurrency limit: {run_concurrency}. Total elapsed time: {duration} seconds."
    )

    # Mark run as finished
    if run_id and run_id in _backup_runs:
        _backup_runs[run_id]['finished'] = True
        _backup_runs[run_id]['finished_at'] = _time.time()
        # Auto-expire after 10 minutes to avoid memory leak
        async def _expire():
            await asyncio.sleep(600)
            _backup_runs.pop(run_id, None)
        asyncio.create_task(_expire())

    # Run retention cleanup after backup
    try:
        _cleanup_expired_snapshots(
            policy_id=policy_id or '',
            max_days=int(policy.get('retention_days', 90)) if policy else None,
            max_per_device=int(policy.get('max_versions_per_device', 30)) if policy else None,
        )
    except Exception as e:
        logger.error(f"[Retention Cleanup] Error: {e}")


# ──────────────────────────────────────────────
# Remote File Archive Manual Sync & Test Endpoints
# ──────────────────────────────────────────────

class TFTPTestPayload(BaseModel):
    server_ip: str = ""
    server_port: int | None = None
    path_prefix: str | None = None
    protocol: str | None = None
    username: str | None = None
    password: str | None = None


class TFTPSettingsPayload(BaseModel):
    enabled: bool = False
    server_ip: str = ""
    server_port: int | None = None
    path_prefix: str = "backups"
    protocol: str | None = None
    username: str = ""
    password: str | None = None


class TFTPSyncSnapshotPayload(BaseModel):
    snapshot_id: str
    server_ip: str = ""
    server_port: int | None = None
    path_prefix: str | None = None
    protocol: str | None = None
    username: str | None = None
    password: str | None = None


class TFTPSyncBatchPayload(BaseModel):
    run_id: str
    server_ip: str = ""
    server_port: int | None = None
    path_prefix: str | None = None
    protocol: str | None = None
    username: str | None = None
    password: str | None = None


def _decrypt_archive_password(value: object) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        from core.crypto import decrypt_credential

        return str(decrypt_credential(raw) or raw)
    except Exception:
        return raw


def _encrypt_archive_password(value: object) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        from core.crypto import encrypt_credential

        return str(encrypt_credential(raw) or raw)
    except Exception:
        return raw


def _read_saved_tftp_settings(conn=None) -> dict:
    from services.file_transfer_service import default_transfer_port, normalize_transfer_protocol

    owns_conn = conn is None
    if owns_conn:
        conn = get_db_connection()
    try:
        row = conn.execute("SELECT value FROM global_vars WHERE key = 'tftp_backup_settings'").fetchone()
        saved = {}
        if row:
            try:
                saved = json.loads(row['value']) or {}
            except Exception:
                saved = {}
    finally:
        if owns_conn:
            conn.close()

    protocol = normalize_transfer_protocol(saved.get('protocol'), default='tftp')
    stored_password = saved.get('password_encrypted') or saved.get('password') or ''
    return {
        'enabled': bool(saved.get('enabled', False)),
        'server_ip': str(saved.get('server_ip') or '').strip(),
        'server_port': int(saved.get('server_port') or default_transfer_port(protocol)),
        'path_prefix': str(saved.get('path_prefix') or 'backups').strip(),
        'protocol': protocol,
        'username': str(saved.get('username') or '').strip(),
        'password': _decrypt_archive_password(stored_password),
    }


def _public_tftp_settings(settings: dict) -> dict:
    return {
        'enabled': bool(settings.get('enabled')),
        'server_ip': str(settings.get('server_ip') or ''),
        'server_port': int(settings.get('server_port') or 69),
        'path_prefix': str(settings.get('path_prefix') or 'backups'),
        'protocol': str(settings.get('protocol') or 'tftp'),
        'username': str(settings.get('username') or ''),
        'password': '',
        'password_configured': bool(settings.get('password')),
    }


def _resolve_tftp_options(payload) -> dict:
    from services.file_transfer_service import default_transfer_port, normalize_transfer_protocol

    saved = _read_saved_tftp_settings()
    protocol = normalize_transfer_protocol(payload.protocol or saved.get('protocol'), default='tftp')
    password = payload.password
    if password is None or password in {'', '***', '••••••', '********'}:
        password = saved.get('password', '')
    return {
        'protocol': protocol,
        'server_ip': str(payload.server_ip or '').strip() or saved.get('server_ip', ''),
        'server_port': int(payload.server_port or saved.get('server_port') or default_transfer_port(protocol)),
        'path_prefix': str(payload.path_prefix if payload.path_prefix is not None else saved.get('path_prefix') or 'backups').strip(),
        'username': str(payload.username if payload.username is not None else saved.get('username') or '').strip(),
        'password': str(password or ''),
    }


def _validate_archive_options(options: dict) -> None:
    from services.file_transfer_service import transfer_protocol_label

    if not options['server_ip']:
        raise HTTPException(status_code=400, detail='未指定文件归档服务器地址，请先配置归档设置')
    if options['protocol'] != 'tftp':
        if not options['username']:
            raise HTTPException(status_code=400, detail=f"{transfer_protocol_label(options['protocol'])} 需要用户名")
        if not options['password']:
            raise HTTPException(status_code=400, detail=f"{transfer_protocol_label(options['protocol'])} 需要密码")


@router.get('/configs/tftp/settings')
def get_tftp_settings():
    return {"success": True, "data": _public_tftp_settings(_read_saved_tftp_settings())}


@router.put('/configs/tftp/settings')
def save_tftp_settings(payload: TFTPSettingsPayload):
    conn = get_db_connection()
    try:
        current = _read_saved_tftp_settings(conn)
        from services.file_transfer_service import default_transfer_port, normalize_transfer_protocol

        protocol = normalize_transfer_protocol(payload.protocol or current.get('protocol'), default='tftp')
        password = payload.password
        if password is None or password in {'', '***', '••••••', '********'}:
            password = current.get('password', '')
        settings_payload = {
            'enabled': bool(payload.enabled),
            'server_ip': payload.server_ip.strip(),
            'server_port': int(payload.server_port or default_transfer_port(protocol)),
            'path_prefix': payload.path_prefix.strip() or 'backups',
            'protocol': protocol,
            'username': payload.username.strip(),
            'password_encrypted': _encrypt_archive_password(password),
        }
        val = json.dumps(settings_payload, ensure_ascii=False)
        row = conn.execute("SELECT id FROM global_vars WHERE key = 'tftp_backup_settings'").fetchone()
        now_ts = _utc_now_iso()
        if row:
            conn.execute("UPDATE global_vars SET value = ?, updated_at = ? WHERE key = 'tftp_backup_settings'", (val, now_ts))
        else:
            var_id = f"gv-{uuid.uuid4().hex[:12]}"
            conn.execute("INSERT INTO global_vars (id, key, value, created_at, updated_at) VALUES (?, 'tftp_backup_settings', ?, ?, ?)",
                         (var_id, val, now_ts, now_ts))
        conn.commit()
        return {"success": True, "message": "文件归档配置已保存", "data": _public_tftp_settings({**settings_payload, 'password': password})}
    finally:
        conn.close()


@router.post('/configs/tftp/test')
async def test_tftp_connectivity(payload: TFTPTestPayload):
    options = _resolve_tftp_options(payload)
    _validate_archive_options(options)
    from services.file_transfer_service import upload_bytes
    probe_name = f"{options['path_prefix'].strip('/')}/_probe_test_{uuid.uuid4().hex[:6]}.tmp" if options['path_prefix'].strip() else f"_probe_test_{uuid.uuid4().hex[:6]}.tmp"
    probe_data = f"Nexora archive probe\nTimestamp: {_utc_now_iso()}\nServer: {options['server_ip']}\n".encode('utf-8')
    ok, msg = await asyncio.to_thread(
        upload_bytes,
        protocol=options['protocol'],
        server_ip=options['server_ip'],
        data=probe_data,
        remote_filename=probe_name,
        server_port=options['server_port'],
        username=options['username'],
        password=options['password'],
        timeout=3.0,
        retries=2,
    )
    if not ok:
        return {"success": False, "message": f"{options['protocol'].upper()} 连接探测失败: {msg}"}
    return {"success": True, "message": f"{options['protocol'].upper()} 文件服务器连接探测成功！({msg})"}


@router.post('/configs/tftp/sync-snapshot')
async def sync_snapshot_to_tftp(payload: TFTPSyncSnapshotPayload):
    conn = get_db_connection()
    try:
        snap = conn.execute("SELECT * FROM config_snapshots WHERE id = ?", (payload.snapshot_id,)).fetchone()
        if not snap:
            raise HTTPException(status_code=404, detail="快照不存在")
        file_path = snap['file_path']
        hostname = snap['hostname']
        config_type = snap['config_type'] if 'config_type' in snap.keys() else 'running'
    finally:
        conn.close()

    options = _resolve_tftp_options(payload)
    _validate_archive_options(options)

    abs_path = os.path.join(BACKUP_ROOT, file_path.replace('/', os.sep).replace('\\', os.sep))
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="底层配置文件不存在")

    remote_name = os.path.basename(file_path)
    target_path = f"{options['path_prefix'].strip('/')}/{remote_name}" if options['path_prefix'].strip() else remote_name

    content = _read_config_file(file_path)
    if not content:
        raise HTTPException(status_code=500, detail="配置文件解密失败或内容为空，未上传")

    from services.file_transfer_service import upload_bytes
    ok, msg = await asyncio.to_thread(
        upload_bytes,
        protocol=options['protocol'],
        server_ip=options['server_ip'],
        data=content.encode('utf-8'),
        remote_filename=target_path,
        server_port=options['server_port'],
        username=options['username'],
        password=options['password'],
    )

    if not ok:
        raise HTTPException(status_code=500, detail=f"{options['protocol'].upper()} 上传失败: {msg}")

    return {
        "success": True,
        "message": f"成功将 {hostname} 的 {config_type} 配置上传至 {options['protocol'].upper()} ({options['server_ip']}:{options['server_port']}/{target_path})",
        "remote_path": target_path,
    }


@router.post('/configs/tftp/sync-batch')
async def sync_batch_to_tftp(payload: TFTPSyncBatchPayload):
    conn = get_db_connection()
    try:
        run = conn.execute("SELECT * FROM config_backup_runs WHERE id = ?", (payload.run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="备份批次不存在")
        snapshots = conn.execute("SELECT file_path, hostname FROM config_snapshots WHERE task_id = ?", (payload.run_id,)).fetchall()
    finally:
        conn.close()

    options = _resolve_tftp_options(payload)
    _validate_archive_options(options)

    items = []
    for s in snapshots:
        rel_path = s['file_path']
        abs_path = os.path.join(BACKUP_ROOT, rel_path.replace('/', os.sep).replace('\\', os.sep))
        if os.path.isfile(abs_path):
            content = _read_config_file(rel_path)
            if content:
                items.append({
                    'local_path': abs_path,
                    'remote_name': os.path.basename(rel_path),
                    'archive_name': rel_path,
                    'hostname': s['hostname'],
                    'data': content.encode('utf-8'),
                })
            else:
                logger.warning("[Archive Sync] Could not decode snapshot %s; skipping remote upload", rel_path)

    if not items:
        raise HTTPException(status_code=400, detail="该批次没有可上传的有效备份快照文件")

    from services.file_transfer_service import batch_upload_configs
    remote_archive_name = _config_archive_name(payload.run_id)
    summary_text = (
        f"Nexora Config Backup Manual Archive Summary\n"
        f"Run ID: {payload.run_id}\n"
        f"Triggered At: {_utc_now_iso()}\n"
        f"Archive File: {remote_archive_name}\n"
        f"Files In Archive: {len(items)}\n"
    )
    tftp_res = await asyncio.to_thread(
        batch_upload_configs,
        protocol=options['protocol'],
        server_ip=options['server_ip'],
        items=items,
        server_port=options['server_port'],
        username=options['username'],
        password=options['password'],
        path_prefix=options['path_prefix'],
        summary_log=summary_text,
        archive_name=remote_archive_name,
    )

    tftp_status = tftp_res.get('status', 'failed')
    archive_file_count = tftp_res.get('file_count', len(items))
    archive_uploaded_count = tftp_res.get('uploaded', 0)
    tftp_uploaded_count = archive_file_count if tftp_status in ('success', 'partial') else 0
    tftp_log = "\n".join(tftp_res.get('details', []))

    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE config_backup_runs
            SET tftp_status = ?, tftp_server = ?, tftp_log = ?, tftp_uploaded_count = ?
            WHERE id = ?
            """,
        (tftp_status, options['server_ip'], tftp_log, tftp_uploaded_count, payload.run_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "success": tftp_status in ('success', 'partial'),
        "status": tftp_status,
        "uploaded": archive_uploaded_count,
        "archive_count": archive_uploaded_count,
        "total": tftp_res.get('total', 1),
        "file_count": archive_file_count,
        "archive_name": tftp_res.get('archive_name', remote_archive_name),
        "details": tftp_res.get('details', []),
        "message": (
            f"{options['protocol'].upper()} 同步完成: 成功上传 {tftp_uploaded_count} 个归档包，"
            f"包含 {archive_file_count} 个配置文件至 {options['server_ip']}:{options['server_port']}"
        ),
    }
