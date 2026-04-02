"""
configs.py — Config Snapshot API
Stores config files in: backup/YYYY/MM/Vendor/Hostname/YYYYMMDD_HHMMSS_trigger.cfg
Stores metadata in SQLite table config_snapshots.
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

logger = logging.getLogger(__name__)

router = APIRouter()

# Backup root directory — relative to cwd (d:\netops-automation)
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
    hour: int = 2
    minute: int = 0


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
        pass  # Encryption key not configured — store plaintext
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
    """Return devices that have at least one config snapshot, with backup count and pagination."""
    conn = get_db_connection()
    try:
        where_sql = ''
        params: list = []
        if search and search.strip():
            fuzzy = f"%{search.strip().lower()}%"
            where_sql = "AND (LOWER(d.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)"
            params = [fuzzy, fuzzy]

        count_sql = f'''
            SELECT COUNT(DISTINCT d.id)
            FROM devices d
            INNER JOIN config_snapshots cs ON cs.device_id = d.id
            WHERE 1=1 {where_sql}
        '''
        total = conn.execute(count_sql, tuple(params)).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(f'''
            SELECT d.id, d.hostname, d.ip_address, d.platform, d.status,
                   COUNT(cs.id) AS backup_count,
                   MAX(cs.timestamp) AS latest_backup
            FROM devices d
            INNER JOIN config_snapshots cs ON cs.device_id = d.id
            WHERE 1=1 {where_sql}
            GROUP BY d.id
            ORDER BY MAX(cs.timestamp) DESC
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
            where_clauses.append("(LOWER(cs.hostname) LIKE ? OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)")
            params.extend([fuzzy, fuzzy])

        filter_sql = ''
        if where_clauses:
            filter_sql = ' AND ' + ' AND '.join(where_clauses)

        count_sql = f'''
            SELECT COUNT(DISTINCT cs.device_id)
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
            INNER JOIN (
                SELECT device_id, MAX(timestamp) AS max_ts
                FROM config_snapshots GROUP BY device_id
            ) latest ON cs.device_id = latest.device_id AND cs.timestamp = latest.max_ts
            WHERE 1=1 {filter_sql}
        '''
        total = conn.execute(count_sql, tuple(params)).fetchone()[0]

        offset = (page - 1) * page_size
        data_sql = f'''
            SELECT cs.id, cs.device_id, cs.hostname, cs.vendor, cs.trigger,
                   cs.timestamp, cs.size, d.ip_address, d.status AS device_status,
                   d.platform
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
            INNER JOIN (
                SELECT device_id, MAX(timestamp) AS max_ts
                FROM config_snapshots GROUP BY device_id
            ) latest ON cs.device_id = latest.device_id AND cs.timestamp = latest.max_ts
            WHERE 1=1 {filter_sql}
            ORDER BY cs.timestamp DESC
            LIMIT ? OFFSET ?
        '''
        rows = conn.execute(data_sql, tuple([*params, page_size, offset])).fetchall()

        items = []
        for r in rows:
            items.append({
                'id': r['id'],
                'device_id': r['device_id'],
                'hostname': r['hostname'],
                'ip_address': r['ip_address'] or '',
                'vendor': r['vendor'] or '',
                'platform': r['platform'] or '',
                'device_status': r['device_status'] or 'unknown',
                'trigger': r['trigger'] or '',
                'timestamp': r['timestamp'],
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
DEFAULT_SCHEDULE = {'enabled': True, 'hour': 2, 'minute': 0}


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
    return _get_schedule_from_db()


@router.put('/configs/schedule')
def update_schedule(body: ScheduleUpdate):
    cfg = {'enabled': body.enabled, 'hour': body.hour, 'minute': body.minute}
    _save_schedule_to_db(cfg)
    # Reschedule in-process APScheduler job
    try:
        from main import reschedule_backup
        reschedule_backup(cfg)
    except Exception as e:
        logger.warning(f"Could not reschedule: {e}")
    return cfg


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
                   WHERE device_id = ? ORDER BY timestamp DESC LIMIT -1 OFFSET ?''',
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


# ──────────────────────────────────────────────
# Core backup logic — called by scheduler & manual triggers
# ──────────────────────────────────────────────

MOCK_IPS = {'127.0.0.1', '0.0.0.0', 'localhost'}


async def run_scheduled_backup():
    """Backup all online devices. Called by APScheduler.
    Skips mock/loopback IPs, uses 120s timeout with 1 retry, validates output.
    Runs retention cleanup afterward.
    """
    import httpx
    import asyncio

    logger.info("[Scheduled Backup] Starting daily config backup for all online devices...")
    conn = get_db_connection()
    try:
        devices = conn.execute(
            "SELECT id, hostname, ip_address, platform FROM devices WHERE status = 'online'"
        ).fetchall()
    finally:
        conn.close()

    success = 0
    failed = 0
    skipped = 0

    for device in devices:
        # Skip mock / loopback devices
        if (device['ip_address'] or '') in MOCK_IPS:
            skipped += 1
            logger.info(f"[Scheduled Backup] ⊘ {device['hostname']} (mock IP, skipped)")
            continue

        _platform = (device['platform'] or '').lower()
        if 'cisco' in _platform or 'arista' in _platform or 'rgos' in _platform:
            _backup_cmd = 'show running-config'
        elif 'juniper' in _platform or 'junos' in _platform:
            _backup_cmd = 'show configuration'
        else:
            _backup_cmd = 'display current-configuration'

        output = ''
        backup_ok = False
        max_retries = 2

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        'http://localhost:8003/api/execute',
                        json={'device_id': device['id'], 'command': _backup_cmd, 'isConfig': False}
                    )
                    if resp.status_code == 200:
                        output = resp.json().get('output', '')
                    else:
                        output = ''
            except Exception as e:
                logger.warning(f"[Scheduled Backup] Attempt {attempt + 1} failed for {device['hostname']}: {e}")
                output = ''

            # Validate: reject mock output, error placeholders, or empty
            if output and not output.startswith('[Mock ') and not output.startswith('% '):
                backup_ok = True
                break

            if attempt < max_retries - 1:
                await asyncio.sleep(5)

        if not backup_ok:
            failed += 1
            logger.error(f"[Scheduled Backup] ✗ {device['hostname']}: no valid config obtained")
            continue

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
            success += 1
            logger.info(f"[Scheduled Backup] ✓ {device['hostname']}")
        except Exception as e:
            failed += 1
            logger.error(f"[Scheduled Backup] ✗ {device['hostname']}: {e}")

    logger.info(f"[Scheduled Backup] Done — {success} succeeded, {failed} failed, {skipped} skipped")

    # Run retention cleanup after backup
    try:
        _cleanup_expired_snapshots()
    except Exception as e:
        logger.error(f"[Retention Cleanup] Error: {e}")
