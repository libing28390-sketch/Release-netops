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
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from database import get_db_connection
from services.audit_service import log_audit_event
from core.config import settings
from core.scheduler_manager import scheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

router = APIRouter()

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


def _write_config_file(vendor: str, hostname: str, ts: datetime, trigger: str, content: str) -> str:
    """Write config to disk (gzip compressed, optionally encrypted); return relative file path from BACKUP_ROOT."""
    dir_path = _resolve_backup_dir(vendor, hostname, ts)
    os.makedirs(dir_path, exist_ok=True)
    filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{trigger}.cfg"
    abs_path = os.path.join(dir_path, filename)
    data = gzip.compress(content.encode('utf-8'))
    # Encrypt backup files if a valid encryption key is configured
    try:
        from core.crypto import _get_fernet
        f = _get_fernet()
        data = b'ENCRYPTED:' + f.encrypt(data)
    except Exception:
        pass  # Encryption key not configured - store plaintext
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


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@router.get('/configs/devices-with-backups')
def list_devices_with_backups(
    search: str = Query(default='', description='Search hostname or IP'),
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
        if search and search.strip():
            fuzzy = f"%{search.strip().lower()}%"
            where_sql += " AND (LOWER(d.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)"
            params.extend([fuzzy, fuzzy])

        count_sql = f'''
            SELECT COUNT(DISTINCT d.id)
            FROM devices d
            {where_sql}
        '''
        total = conn.execute(count_sql, tuple(params)).fetchone()[0]

        offset = (page - 1) * page_size
        # Devices sorted by whether they've been backed up (backed-up first),
        # then by most recent backup time, then by hostname.
        rows = conn.execute(f'''
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.status,
                   COUNT(cs.id) AS backup_count,
                   MAX(cs.timestamp) AS latest_backup
            FROM devices d
            LEFT JOIN config_snapshots cs ON cs.device_id = d.id
            {where_sql}
            GROUP BY d.id
            ORDER BY
                CASE WHEN COUNT(cs.id) > 0 THEN 0 ELSE 1 END,
                COALESCE(MAX(cs.timestamp), '') DESC,
                d.hostname
            LIMIT ? OFFSET ?
        ''', tuple([*params, page_size, offset])).fetchall()

        return {
            'items': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()


@router.get('/configs/snapshots')
def list_snapshots(device_id: str = None, hostname: str = None, ip_address: str = None, q: str = None):
    """List all snapshot metadata (no content)."""
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if device_id:
            where_clauses.append('cs.device_id = ?')
            params.append(device_id)

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
                   d.platform, cs.id AS snapshot_id, cs.timestamp, cs.size, cs.trigger
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
            })

        return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
    finally:
        conn.close()


@router.post('/configs/snapshots', status_code=201)
def create_snapshot(body: SnapshotCreate):
    """Save a config snapshot to file + DB."""
    ts = datetime.now()
    snap_id = f"snap-{uuid.uuid4().hex[:12]}"
    rel_path = _write_config_file(body.vendor, body.hostname, ts, body.trigger, body.content)
    size = len(body.content.encode('utf-8'))

    conn = get_db_connection()
    try:
        conn.execute(
            '''INSERT INTO config_snapshots
               (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (snap_id, body.device_id, body.hostname, body.vendor,
             ts.isoformat(), body.trigger, body.author, body.tag or '',
             rel_path, size)
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
        details={'trigger': body.trigger, 'vendor': body.vendor, 'size': size},
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
    return {
        'id': snap_id,
        'content': content,
        'hostname': row['hostname'],
        'vendor': row['vendor'] or '',
        'timestamp': row['timestamp'],
        'trigger': row['trigger'] or '',
        'device_id': row['device_id'],
        'size': row['size'] or 0,
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
        now = datetime.now()
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

        # Today's failures - online devices without today's backup
        all_device_ids = conn.execute(
            "SELECT id FROM devices WHERE status = 'online'"
        ).fetchall()
        today_backed_ids = conn.execute(
            "SELECT DISTINCT device_id FROM config_snapshots WHERE timestamp >= ?",
            (today_start,)
        ).fetchall()
        today_backed_set = {r['device_id'] for r in today_backed_ids}
        today_failed = sum(1 for r in all_device_ids if r['id'] not in today_backed_set)

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
                    'total': today_total,
                    'scheduled': today_scheduled,
                    'manual': today_manual,
                    'success': today_total,
                    'failed': today_failed,
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
        cron = croniter(cron_expr, datetime.now())
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
    max_days: int = 90
    max_per_device: int = 30


def _get_retention_from_db() -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT value FROM global_vars WHERE key = ?", (RETENTION_KEY,)
        ).fetchone()
        if row:
            return json.loads(row['value'])
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


def _cleanup_expired_snapshots():
    """Delete snapshots that exceed retention policy (by age and per-device count)."""
    retention = _get_retention_from_db()
    max_days = retention.get('max_days', 90)
    max_per_device = retention.get('max_per_device', 30)
    deleted = 0

    conn = get_db_connection()
    try:
        # 1. Delete snapshots older than max_days
        cutoff = (datetime.now() - timedelta(days=max_days)).isoformat()
        old = conn.execute(
            'SELECT id, file_path FROM config_snapshots WHERE timestamp < ?', (cutoff,)
        ).fetchall()
        for s in old:
            _delete_config_file(s['file_path'])
        if old:
            conn.execute('DELETE FROM config_snapshots WHERE timestamp < ?', (cutoff,))
            deleted += len(old)

        # 2. Per-device: keep only max_per_device most recent
        devs = conn.execute('SELECT DISTINCT device_id FROM config_snapshots').fetchall()
        for d in devs:
            excess = conn.execute(
                '''SELECT id, file_path FROM config_snapshots
                   WHERE device_id = ? ORDER BY timestamp DESC LIMIT 1000 OFFSET ?''',
                (d['device_id'], max_per_device)
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
        logger.info(f"[Retention Cleanup] Removed {deleted} expired snapshots")


def reschedule_backup(cfg: dict):
    """
    Called when the user changes the schedule settings.
    Updates the APScheduler job 'daily_backup'.
    """
    if scheduler.get_job('daily_backup'):
        scheduler.remove_job('daily_backup')
    
    if cfg.get('enabled', True):
        cron_expr = cfg.get('cron', '')
        if not cron_expr:
            # Fallback for old format
            h = cfg.get('hour', 2)
            m = cfg.get('minute', 0)
            cron_expr = f'{m} {h} * * *'
            
        parts = cron_expr.split()
        if len(parts) >= 5:
            trigger = CronTrigger(
                minute=parts[0], hour=parts[1],
                day=parts[2], month=parts[3], day_of_week=parts[4],
            )
        else:
            trigger = CronTrigger(hour=cfg.get('hour', 2), minute=cfg.get('minute', 0))
            
        scheduler.add_job(
            run_scheduled_backup,
            trigger,
            id='daily_backup',
            name='Scheduled Config Backup',
            replace_existing=True,
        )
    else:
        logger.info("[Scheduler] Scheduled backup disabled")


# ──────────────────────────────────────────────
# Core backup logic - called by scheduler & manual triggers
# ──────────────────────────────────────────────

MOCK_IPS = {'127.0.0.1', '0.0.0.0', 'localhost'}


async def run_scheduled_backup(run_id: str | None = None):
    """Backup all online network devices. Called by APScheduler or on-demand.

    Concurrency:
      - Up to ``BACKUP_CONCURRENCY`` (default 10) devices are backed up in
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

    start_time = _time.time()
    logger.info(f"[Scheduled Backup] Starting config backup task. Concurrency limit: {BACKUP_CONCURRENCY} devices at a time.")
    conn = get_db_connection()
    try:
        devices = conn.execute(
            "SELECT id, hostname, ip_address, platform, vendor, role, username, password, "
            "normal_username, normal_password, admin_username, admin_password, enable_password, "
            "credential_id, credential_source, vault_path, management_port "
            "FROM devices WHERE status = 'online'"
        ).fetchall()
    finally:
        conn.close()

    # Platforms we back up (anything producing a textual running-config).
    NETWORK_PLATFORM_KEYWORDS = (
        'cisco', 'arista', 'rgos', 'ruijie',
        'juniper', 'junos',
        'huawei', 'vrp',
        'h3c', 'comware',
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
    sem = asyncio.Semaphore(BACKUP_CONCURRENCY)

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
        """Back up a single device; returns a result dict."""
        nonlocal success_count, failed_count

        from core.platform_utils import normalize_device_platform
        _platform = normalize_device_platform(device.get('vendor'), device.get('platform'))
        if 'cisco' in _platform or 'arista' in _platform or 'rgos' in _platform or 'ruijie' in _platform:
            _backup_cmd = 'show running-config'
        elif 'juniper' in _platform or 'junos' in _platform:
            _backup_cmd = 'show configuration'
        else:
            _backup_cmd = 'display current-configuration'

        d = dict(device)
        d['platform'] = _platform
        d['conn_timeout'] = 8  # Use a shorter connection timeout of 8s for backup tasks to fail fast
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
                'detail': '该设备没有配置可用的用户名或密码凭证。'
            }

        d['username'] = username
        d['password'] = password
        d['enable_password'] = enable_pass
        cred_kind = 'resolved'

        output = ''
        backup_ok = False

        async with sem:
            try:
                driver_type = 'mock' if d.get('ip_address') in ['127.0.0.1', '0.0.0.0'] else 'netmiko'
                service = AutomationService(driver_type=driver_type)
                commands = [_backup_cmd]

                # Use the built-in ThreadPoolExecutor with 50 workers from ExecutionOrchestrator
                # instead of the event loop's default thread pool (which is limited by CPU cores)
                results = await asyncio.get_event_loop().run_in_executor(
                    service.orchestrator.executor,
                    lambda: service.execute_commands(d, commands, is_config=False)
                )

                if results and results[0].get('success', False):
                    output = results[0].get('output') or results[0].get('stdout') or ''
                    _record_instant_execution(d['id'], "Scheduled Backup", commands, 'completed',
                                              platform=d.get('platform'), output=output, device_info=d)
                else:
                    err = (results[0].get('error') or results[0].get('stderr') or 'Unknown error') if results else 'Unknown error'
                    logger.warning(f"[Scheduled Backup] Execution failed for {device['hostname']} ({cred_kind}): {err}")
                    output = ''

            except Exception as e:
                logger.warning(f"[Scheduled Backup] Logic error for {device['hostname']}: {e}")
                output = ''

        if not _looks_like_error(output) and not output.startswith('% '):
            backup_ok = True

        if not backup_ok:
            failed_count += 1
            logger.error(
                f"[Scheduled Backup] [X] {device['hostname']} ({cred_kind}): "
                f"no valid config obtained (output length={len(output)})"
            )
            
            # Determine error reason
            err_str = 'Unknown error'
            if results and results[0]:
                err_str = results[0].get('error') or results[0].get('stderr') or 'No config output'
            elif results is None:
                err_str = 'No connection could be established'

            from drivers.ssh_compat import get_ssh_error_code, build_ssh_error_guidance
            err_code = get_ssh_error_code(str(err_str))
            detail_reason = build_ssh_error_guidance(str(err_str))

            if err_code == 'legacy_ssh_algorithms':
                short_reason = 'SSH协商失败'
            elif err_code == 'ssh_authentication_failed':
                short_reason = '认证失败'
            elif err_code == 'ssh_transport_timeout':
                short_reason = '网络超时'
            elif err_code == 'ssh_transport_unreachable':
                short_reason = '连接被拒'
            else:
                short_reason = '无法获取配置'

            return {
                'hostname': device['hostname'],
                'status': 'failed',
                'reason': short_reason,
                'detail': detail_reason
            }

        try:
            platform = (device['platform'] or '').lower()
            if 'cisco' in platform:
                vendor = 'Cisco'
            elif 'juniper' in platform or 'junos' in platform:
                vendor = 'Juniper'
            elif 'huawei' in platform:
                vendor = 'Huawei'
            elif 'arista' in platform or 'eos' in platform:
                vendor = 'Arista'
            else:
                vendor = 'Other'

            ts = datetime.now()
            rel_path = _write_config_file(vendor, device['hostname'], ts, 'scheduled', output)
            size = len(output.encode('utf-8'))
            snap_id = f"snap-{uuid.uuid4().hex[:12]}"
            conn2 = get_db_connection()
            try:
                conn2.execute(
                    '''INSERT INTO config_snapshots
                       (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (snap_id, device['id'], device['hostname'], vendor,
                     ts.isoformat(), 'scheduled', 'system', '', rel_path, size)
                )
                conn2.commit()
            finally:
                conn2.close()
            success_count += 1
            logger.info(f"[Scheduled Backup] [OK] {device['hostname']}")
            return {'hostname': device['hostname'], 'status': 'success', 'size': size}
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
        result = await _backup_one(device)
        if run_id and run_id in _backup_runs:
            entry = _backup_runs[run_id]
            entry['done'] += 1
            entry['success'] = success_count
            entry['failed'] = failed_count
            entry['devices'].append(result)
        return result

    await asyncio.gather(*[_run_with_progress(dev) for dev in eligible])

    duration = round(_time.time() - start_time, 2)
    logger.info(
        f"[Scheduled Backup] Done - {success_count} succeeded, {failed_count} failed, {skipped_count} skipped. "
        f"Concurrency limit: {BACKUP_CONCURRENCY}. Total elapsed time: {duration} seconds."
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
        _cleanup_expired_snapshots()
    except Exception as e:
        logger.error(f"[Retention Cleanup] Error: {e}")
