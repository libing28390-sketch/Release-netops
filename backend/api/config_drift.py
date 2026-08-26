"""
config_drift.py — Configuration Drift Detection & Selective Rollback API
Compares device running-config against baseline snapshots to detect drift.
"""

import os
import uuid
import difflib
import logging
import threading
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db_connection
from core.rbac import require_role

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Drift scan execution
# ──────────────────────────────────────────────────────────────────────
# A full drift scan walks every device with snapshots, reads two files
# from disk per device, and writes a row into `config_drift_results`.
# At 1 k+ devices that easily takes tens of seconds, blocking the FastAPI
# worker if done in-request. We therefore expose two paths:
#   * `/config-drift/scan`         — fire-and-forget; returns the latest
#                                    cached results immediately and kicks
#                                    off a background scan if stale.
#   * `/config-drift/scan?force=1` — start a fresh scan in the background.
#
# Lock + last-finished timestamp so concurrent triggers don't pile up.
_drift_scan_lock = threading.Lock()
_drift_scan_in_progress: dict = {'running': False, 'started_at': None, 'finished_at': None}


def _run_drift_scan_sync():
    """The full per-device scan, run in a worker thread. Writes results
    into `config_drift_results` so the GET endpoint can serve them without
    re-running the scan."""
    conn = get_db_connection()
    try:
        devices = conn.execute('''
            SELECT DISTINCT cs.device_id, cs.hostname, d.ip_address, d.platform, d.status
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
        ''').fetchall()
        now_iso = datetime.utcnow().isoformat()

        for dev in devices:
            device_id = dev['device_id']
            snaps = conn.execute('''
                SELECT id, timestamp, trigger, file_path
                FROM config_snapshots
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
            ''', (device_id,)).fetchall()

            if not snaps:
                continue
            current_snap = snaps[0]
            designated = conn.execute(
                """
                SELECT cs.id, cs.timestamp, cs.trigger, cs.file_path
                FROM config_baselines cb
                JOIN config_snapshots cs ON cs.id = cb.snapshot_id
                WHERE cb.device_id = ? AND cb.config_type = 'running'
                """,
                (device_id,),
            ).fetchone()
            if designated:
                baseline_snap = designated
                baseline_source = 'designated'
            elif len(snaps) >= 2:
                baseline_snap = snaps[1]
                baseline_source = 'previous'
            else:
                continue

            current_content = _read_config_file(current_snap['file_path']) if current_snap['file_path'] else ''
            baseline_content = _read_config_file(baseline_snap['file_path']) if baseline_snap['file_path'] else ''

            if not current_content or not baseline_content:
                drift_status = 'error'
                added = removed = changed = 0
            else:
                diff_result = _compute_diff(baseline_content, current_content, normalize=True)
                added = diff_result['added']
                removed = diff_result['removed']
                changed = diff_result['changed']
                drift_status = 'drifted' if diff_result['has_drift'] else 'compliant'

            drift_id = f"drift-{uuid.uuid4().hex[:12]}"
            conn.execute('''
                INSERT INTO config_drift_results
                (id, device_id, hostname, baseline_snapshot_id, current_snapshot_id,
                 drift_status, added_lines, removed_lines, changed_lines, diff_summary, checked_at,
                 baseline_source, diff_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                  device_id=excluded.device_id, hostname=excluded.hostname,
                  baseline_snapshot_id=excluded.baseline_snapshot_id,
                  current_snapshot_id=excluded.current_snapshot_id,
                  drift_status=excluded.drift_status, added_lines=excluded.added_lines,
                  removed_lines=excluded.removed_lines, changed_lines=excluded.changed_lines,
                  diff_summary=excluded.diff_summary, checked_at=excluded.checked_at,
                  baseline_source=excluded.baseline_source, diff_mode=excluded.diff_mode
            ''', (drift_id, device_id, dev['hostname'] or '', baseline_snap['id'],
                  current_snap['id'], drift_status, added, removed, changed, '', now_iso,
                  baseline_source, 'normalized'))

        conn.commit()
    except Exception as exc:
        logger.exception("[drift] background scan failed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        with _drift_scan_lock:
            _drift_scan_in_progress['running'] = False
            _drift_scan_in_progress['finished_at'] = datetime.utcnow().isoformat()


def _kick_off_drift_scan() -> bool:
    """Start a drift scan in a daemon thread if one isn't already running.
    Returns True if a scan was started, False if one was already in flight."""
    with _drift_scan_lock:
        if _drift_scan_in_progress['running']:
            return False
        _drift_scan_in_progress['running'] = True
        _drift_scan_in_progress['started_at'] = datetime.utcnow().isoformat()
        _drift_scan_in_progress['finished_at'] = None
    threading.Thread(target=_run_drift_scan_sync, daemon=True, name='drift-scan').start()
    return True


def _read_cached_drift_results() -> list[dict]:
    """Read the latest drift results for every device from
    `config_drift_results` in a single query. Falls back to an empty list
    if the table doesn't exist yet."""
    conn = get_db_connection()
    try:
        rows = conn.execute('''
            SELECT r.device_id, r.hostname, r.drift_status, r.added_lines,
                   r.removed_lines, r.changed_lines, r.checked_at,
                   r.baseline_snapshot_id, r.current_snapshot_id,
                   r.baseline_source, r.diff_mode,
                   d.ip_address, d.platform, d.status as device_status
            FROM config_drift_results r
            LEFT JOIN devices d ON d.id = r.device_id
            ORDER BY r.checked_at DESC
        ''').fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.debug("[drift] failed reading cached results: %s", exc)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

router = APIRouter()

BACKUP_ROOT = os.path.join(os.getcwd(), 'backup')


def _read_config_file(file_path: str) -> str:
    abs_path = os.path.join(BACKUP_ROOT, file_path.replace('/', os.sep).replace('\\', os.sep))
    if not os.path.exists(abs_path):
        return ''
    with open(abs_path, 'rb') as fh:
        data = fh.read()
    if data.startswith(b'ENCRYPTED:'):
        try:
            from core.crypto import _get_fernet
            f = _get_fernet()
            return f.decrypt(data[len(b'ENCRYPTED:'):]).decode('utf-8')
        except Exception:
            return ''
    return data.decode('utf-8')


def _compute_diff(old_text: str, new_text: str, *, normalize: bool = False):
    """Compute unified diff and return structured result."""
    if normalize:
        from api.configs import _normalize_config_content
        old_text = _normalize_config_content(old_text)
        new_text = _normalize_config_content(new_text)
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile='baseline', tofile='current', lineterm=''))

    added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
    removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

    # Build structured diff blocks
    blocks = []
    current_block = None
    for line in diff:
        if line.startswith('@@'):
            if current_block:
                blocks.append(current_block)
            current_block = {'header': line.strip(), 'lines': []}
        elif current_block is not None:
            if line.startswith('+'):
                current_block['lines'].append({'type': 'add', 'content': line[1:]})
            elif line.startswith('-'):
                current_block['lines'].append({'type': 'remove', 'content': line[1:]})
            else:
                current_block['lines'].append({'type': 'context', 'content': line.lstrip(' ')})
    if current_block:
        blocks.append(current_block)

    return {
        'added': added,
        'removed': removed,
        'changed': min(added, removed),
        'blocks': blocks,
        'has_drift': added > 0 or removed > 0,
    }


# ──────────────────────────────────────────────
# Drift detection endpoints
# ──────────────────────────────────────────────

@router.get('/config-drift/scan')
def scan_all_devices(force: bool = False):
    """Return drift status for every device.

    The heavy work (reading two config files per device, diffing, writing
    `config_drift_results`) is done in a background thread; this endpoint
    serves the cached rows immediately. The frontend can poll without
    blocking the FastAPI worker.

    * If `force=1` is passed, kick off a fresh scan in the background.
    * If results are missing or older than 10 minutes, also kick off a scan
      automatically.
    * Either way, return the current cached snapshot synchronously.
    """
    cached = _read_cached_drift_results()

    # Decide whether to launch a background refresh.
    needs_refresh = bool(force)
    if not needs_refresh:
        if not cached:
            needs_refresh = True
        else:
            try:
                latest = max(
                    (datetime.fromisoformat(r['checked_at']) for r in cached if r.get('checked_at')),
                    default=None,
                )
                if latest is None:
                    needs_refresh = True
                else:
                    age_seconds = (datetime.utcnow() - latest).total_seconds()
                    if age_seconds > 600:  # 10 minutes
                        needs_refresh = True
            except Exception:
                needs_refresh = True

    scan_started = False
    if needs_refresh:
        scan_started = _kick_off_drift_scan()

    items = []
    for r in cached:
        items.append({
            'device_id': r.get('device_id'),
            'hostname': r.get('hostname') or '',
            'ip_address': r.get('ip_address') or '',
            'platform': r.get('platform') or '',
            'device_status': r.get('device_status') or '',
            'drift_status': r.get('drift_status') or 'unknown',
            'added_lines': r.get('added_lines') or 0,
            'removed_lines': r.get('removed_lines') or 0,
            'changed_lines': r.get('changed_lines') or 0,
            'last_checked': r.get('checked_at'),
            'baseline_snapshot_id': r.get('baseline_snapshot_id'),
            'current_snapshot_id': r.get('current_snapshot_id'),
            'baseline_source': r.get('baseline_source') or 'previous',
            'diff_mode': r.get('diff_mode') or 'normalized',
        })

    return {
        'total': len(items),
        'drifted': sum(1 for r in items if r['drift_status'] == 'drifted'),
        'compliant': sum(1 for r in items if r['drift_status'] == 'compliant'),
        'no_baseline': sum(1 for r in items if r['drift_status'] == 'no_baseline'),
        'items': items,
        'scan_in_progress': _drift_scan_in_progress['running'],
        'scan_started': scan_started,
        'last_scan_started_at': _drift_scan_in_progress['started_at'],
        'last_scan_finished_at': _drift_scan_in_progress['finished_at'],
    }


@router.get('/config-drift/device/{device_id}/diff')
def get_device_diff(
    device_id: str,
    baseline_id: Optional[str] = None,
    current_id: Optional[str] = None,
    mode: str = Query(default='normalized', pattern='^(raw|normalized)$'),
):
    """Get detailed line-by-line diff between two snapshots of a device."""
    conn = get_db_connection()
    try:
        if not baseline_id or not current_id:
            # Use the designated baseline when present; otherwise compare the
            # two latest snapshots for backwards compatibility.
            snaps = conn.execute('''
                SELECT id, timestamp, trigger, file_path, hostname, vendor
                FROM config_snapshots
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
            ''', (device_id,)).fetchall()
            if not snaps:
                raise HTTPException(status_code=404, detail='No snapshots found')
            current_snap = dict(snaps[0])
            designated = conn.execute(
                """
                SELECT cs.*
                FROM config_baselines cb
                JOIN config_snapshots cs ON cs.id = cb.snapshot_id
                WHERE cb.device_id = ? AND cb.config_type = 'running'
                """,
                (device_id,),
            ).fetchone()
            if designated:
                baseline_snap = dict(designated)
                baseline_source = 'designated'
            elif len(snaps) >= 2:
                baseline_snap = dict(snaps[1])
                baseline_source = 'previous'
            else:
                raise HTTPException(status_code=404, detail='No designated baseline and only one snapshot exists')
        else:
            baseline_row = conn.execute('SELECT * FROM config_snapshots WHERE id = ?', (baseline_id,)).fetchone()
            current_row = conn.execute('SELECT * FROM config_snapshots WHERE id = ?', (current_id,)).fetchone()
            if not baseline_row or not current_row:
                raise HTTPException(status_code=404, detail='Snapshot not found')
            baseline_snap = dict(baseline_row)
            current_snap = dict(current_row)
            if baseline_snap.get('device_id') != device_id or current_snap.get('device_id') != device_id:
                raise HTTPException(status_code=400, detail='Snapshots must belong to the requested device')
            baseline_source = 'explicit'
    finally:
        conn.close()

    baseline_content = _read_config_file(baseline_snap['file_path']) if baseline_snap.get('file_path') else ''
    current_content = _read_config_file(current_snap['file_path']) if current_snap.get('file_path') else ''

    diff_result = _compute_diff(
        baseline_content,
        current_content,
        normalize=mode == 'normalized',
    )

    return {
        'device_id': device_id,
        'hostname': current_snap.get('hostname', ''),
        'mode': mode,
        'baseline_source': baseline_source,
        'baseline': {
            'id': baseline_snap['id'],
            'timestamp': baseline_snap.get('timestamp', ''),
            'trigger': baseline_snap.get('trigger', ''),
        },
        'current': {
            'id': current_snap['id'],
            'timestamp': current_snap.get('timestamp', ''),
            'trigger': current_snap.get('trigger', ''),
        },
        **diff_result,
    }


@router.get('/config-drift/device/{device_id}/snapshots')
def list_device_snapshots(device_id: str):
    """List all config snapshots for a device (for picking baseline/current)."""
    conn = get_db_connection()
    try:
        rows = conn.execute('''
            SELECT cs.id, cs.hostname, cs.vendor, cs.timestamp, cs.trigger, cs.author,
                   cs.tag, cs.size, cs.integrity_status, cs.validation_status,
                   cs.validation_message, cs.config_type, cs.collection_source,
                   cs.collection_task_id, cs.change_ticket_id, cs.line_count,
                   CASE WHEN cb.snapshot_id IS NOT NULL THEN 1 ELSE 0 END AS is_baseline
            FROM config_snapshots cs
            LEFT JOIN config_baselines cb
              ON cb.snapshot_id = cs.id
             AND cb.device_id = cs.device_id
             AND cb.config_type = 'running'
            WHERE cs.device_id = ?
            ORDER BY cs.timestamp DESC
        ''', (device_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


class BaselineRequest(BaseModel):
    snapshot_id: str
    description: str = ''


@router.put('/config-drift/device/{device_id}/baseline')
def set_device_baseline(
    device_id: str,
    body: BaselineRequest,
    user=require_role('Operator'),
):
    conn = get_db_connection()
    try:
        snapshot = conn.execute(
            "SELECT id FROM config_snapshots WHERE id = ? AND device_id = ?",
            (body.snapshot_id, device_id),
        ).fetchone()
        if not snapshot:
            raise HTTPException(status_code=404, detail='Snapshot not found for device')
        conn.execute(
            """
            INSERT INTO config_baselines
            (id, device_id, config_type, snapshot_id, description, set_by, set_at)
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            ON CONFLICT(device_id, config_type) DO UPDATE SET
              snapshot_id = excluded.snapshot_id,
              description = excluded.description,
              set_by = excluded.set_by,
              set_at = excluded.set_at
            """,
            (
                f"baseline-{uuid.uuid4().hex[:16]}",
                device_id,
                body.snapshot_id,
                body.description.strip(),
                user.get('username', ''),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return {'success': True, 'device_id': device_id, 'snapshot_id': body.snapshot_id}
    finally:
        conn.close()


@router.delete('/config-drift/device/{device_id}/baseline')
def clear_device_baseline(device_id: str, _user=require_role('Operator')):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM config_baselines WHERE device_id = ? AND config_type = 'running'",
            (device_id,),
        )
        conn.commit()
        return {'success': True, 'deleted': bool(getattr(cursor, 'rowcount', 0))}
    finally:
        conn.close()


class RollbackRequest(BaseModel):
    device_id: str
    snapshot_id: str
    selected_lines: list[int] = []  # empty = full rollback


@router.post('/config-drift/rollback-preview')
def rollback_preview(body: RollbackRequest):
    """Preview what commands would be applied to rollback to a snapshot.
    If selected_lines is empty, returns the full baseline config.
    If selected_lines is provided, returns only the selected removed lines as commands to re-apply."""
    conn = get_db_connection()
    try:
        snap = conn.execute('SELECT * FROM config_snapshots WHERE id = ?', (body.snapshot_id,)).fetchone()
        if not snap:
            raise HTTPException(status_code=404, detail='Snapshot not found')
        if str(snap['device_id'] or '') != str(body.device_id):
            raise HTTPException(status_code=400, detail='Snapshot does not belong to the requested device')
        device = conn.execute(
            'SELECT id, hostname, ip_address, platform, status FROM devices WHERE id = ?',
            (body.device_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail='Device not found')

        # Get current (latest) snapshot
        current = conn.execute('''
            SELECT * FROM config_snapshots
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (body.device_id,)).fetchone()
    finally:
        conn.close()

    baseline_content = _read_config_file(snap['file_path']) if snap['file_path'] else ''
    current_content = _read_config_file(current['file_path']) if current and current['file_path'] else ''

    if not baseline_content:
        raise HTTPException(status_code=400, detail='Cannot read baseline snapshot')

    from api.change_orders.helpers import scan_change_commands
    blockers = []
    if (snap['integrity_status'] or 'unknown') != 'verified':
        blockers.append('目标快照尚未通过 SHA-256 完整性校验')
    if not str(device['ip_address'] or '').strip():
        blockers.append('设备缺少可验证的备用管理地址')
    if str(device['status'] or '').lower() not in {'online', 'active'}:
        blockers.append('设备当前不是在线状态')

    if not body.selected_lines:
        preview_lines = baseline_content.splitlines()
        guard = scan_change_commands(preview_lines, device['platform'] or '')
        return {
            'mode': 'full',
            'plan_id': f"recovery-{uuid.uuid4().hex}",
            'commands': preview_lines,
            'line_count': len(preview_lines),
            'executable': False,
            'requires_change_order': True,
            'requires_mfa': True,
            'requires_pre_restore_backup': True,
            'requires_rollback_timer': True,
            'guard': guard,
            'blockers': blockers,
            'snapshot_hash': snap['raw_hash'] or '',
            'integrity_status': snap['integrity_status'] or 'unknown',
            'warning': '全量配置不能作为逐行 CLI 直接下发；必须由厂商恢复驱动、审批工单和 Recovery Guard 执行。',
        }

    # Selective rollback — compute diff and pick specific removed lines
    diff_result = _compute_diff(current_content, baseline_content)
    all_add_lines = []
    line_idx = 0
    for block in diff_result['blocks']:
        for dl in block['lines']:
            if dl['type'] == 'add':
                line_idx += 1
                if line_idx in body.selected_lines:
                    all_add_lines.append(dl['content'].rstrip())

    guard = scan_change_commands(all_add_lines, device['platform'] or '')
    return {
        'mode': 'selective',
        'plan_id': f"recovery-{uuid.uuid4().hex}",
        'commands': all_add_lines,
        'line_count': len(all_add_lines),
        'executable': not blockers and not guard['blocked'],
        'requires_change_order': True,
        'requires_mfa': True,
        'requires_pre_restore_backup': True,
        'requires_rollback_timer': True,
        'guard': guard,
        'blockers': blockers,
        'snapshot_hash': snap['raw_hash'] or '',
        'integrity_status': snap['integrity_status'] or 'unknown',
    }


@router.get('/config-drift/history')
def drift_history(device_id: Optional[str] = None, limit: int = 100):
    """Get historical drift scan results."""
    conn = get_db_connection()
    try:
        sql = '''
            SELECT dr.*, d.ip_address, d.platform
            FROM config_drift_results dr
            LEFT JOIN devices d ON d.id = dr.device_id
        '''
        params = []
        if device_id:
            sql += ' WHERE dr.device_id = ?'
            params.append(device_id)
        sql += ' ORDER BY dr.checked_at DESC LIMIT ?'
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
