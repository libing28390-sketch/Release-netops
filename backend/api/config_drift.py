"""
config_drift.py — Configuration Drift Detection & Selective Rollback API
Compares device running-config against baseline snapshots to detect drift.
"""

import os
import uuid
import difflib
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db_connection

logger = logging.getLogger(__name__)

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


def _compute_diff(old_text: str, new_text: str):
    """Compute unified diff and return structured result."""
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
def scan_all_devices():
    """Run drift scan across all devices that have at least 2 snapshots.
    Compares the latest snapshot against the second-latest (baseline)."""
    conn = get_db_connection()
    try:
        # Get every device that has at least one snapshot
        devices = conn.execute('''
            SELECT DISTINCT cs.device_id, cs.hostname, d.ip_address, d.platform, d.status
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
        ''').fetchall()

        results = []
        now_iso = datetime.utcnow().isoformat()

        for dev in devices:
            device_id = dev['device_id']
            # Get the two most recent snapshots
            snaps = conn.execute('''
                SELECT id, timestamp, trigger, file_path
                FROM config_snapshots
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
            ''', (device_id,)).fetchall()

            if len(snaps) < 2:
                results.append({
                    'device_id': device_id,
                    'hostname': dev['hostname'] or '',
                    'ip_address': dev['ip_address'] or '',
                    'platform': dev['platform'] or '',
                    'device_status': dev['status'] or '',
                    'drift_status': 'no_baseline',
                    'added_lines': 0,
                    'removed_lines': 0,
                    'changed_lines': 0,
                    'last_checked': now_iso,
                    'baseline_time': snaps[0]['timestamp'] if snaps else '',
                    'current_time': '',
                })
                continue

            current_snap = snaps[0]
            baseline_snap = snaps[1]

            current_content = _read_config_file(current_snap['file_path']) if current_snap['file_path'] else ''
            baseline_content = _read_config_file(baseline_snap['file_path']) if baseline_snap['file_path'] else ''

            if not current_content or not baseline_content:
                drift_status = 'error'
                added = removed = changed = 0
            else:
                diff_result = _compute_diff(baseline_content, current_content)
                added = diff_result['added']
                removed = diff_result['removed']
                changed = diff_result['changed']
                drift_status = 'drifted' if diff_result['has_drift'] else 'compliant'

            # Upsert drift result
            drift_id = f"drift-{uuid.uuid4().hex[:12]}"
            conn.execute('''
                INSERT INTO config_drift_results
                (id, device_id, hostname, baseline_snapshot_id, current_snapshot_id,
                 drift_status, added_lines, removed_lines, changed_lines, diff_summary, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                  device_id=excluded.device_id, hostname=excluded.hostname,
                  baseline_snapshot_id=excluded.baseline_snapshot_id,
                  current_snapshot_id=excluded.current_snapshot_id,
                  drift_status=excluded.drift_status, added_lines=excluded.added_lines,
                  removed_lines=excluded.removed_lines, changed_lines=excluded.changed_lines,
                  diff_summary=excluded.diff_summary, checked_at=excluded.checked_at
            ''', (drift_id, device_id, dev['hostname'] or '', baseline_snap['id'],
                  current_snap['id'], drift_status, added, removed, changed, '', now_iso))

            results.append({
                'device_id': device_id,
                'hostname': dev['hostname'] or '',
                'ip_address': dev['ip_address'] or '',
                'platform': dev['platform'] or '',
                'device_status': dev['status'] or '',
                'drift_status': drift_status,
                'added_lines': added,
                'removed_lines': removed,
                'changed_lines': changed,
                'last_checked': now_iso,
                'baseline_time': baseline_snap['timestamp'],
                'current_time': current_snap['timestamp'],
                'baseline_snapshot_id': baseline_snap['id'],
                'current_snapshot_id': current_snap['id'],
            })

        conn.commit()
        return {
            'total': len(results),
            'drifted': sum(1 for r in results if r['drift_status'] == 'drifted'),
            'compliant': sum(1 for r in results if r['drift_status'] == 'compliant'),
            'no_baseline': sum(1 for r in results if r['drift_status'] == 'no_baseline'),
            'items': results,
        }
    finally:
        conn.close()


@router.get('/config-drift/device/{device_id}/diff')
def get_device_diff(device_id: str, baseline_id: Optional[str] = None, current_id: Optional[str] = None):
    """Get detailed line-by-line diff between two snapshots of a device."""
    conn = get_db_connection()
    try:
        if not baseline_id or not current_id:
            # Use two most recent snapshots
            snaps = conn.execute('''
                SELECT id, timestamp, trigger, file_path, hostname, vendor
                FROM config_snapshots
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT 2
            ''', (device_id,)).fetchall()
            if len(snaps) < 2:
                raise HTTPException(status_code=404, detail='Need at least 2 snapshots for diff')
            current_snap = dict(snaps[0])
            baseline_snap = dict(snaps[1])
        else:
            baseline_row = conn.execute('SELECT * FROM config_snapshots WHERE id = ?', (baseline_id,)).fetchone()
            current_row = conn.execute('SELECT * FROM config_snapshots WHERE id = ?', (current_id,)).fetchone()
            if not baseline_row or not current_row:
                raise HTTPException(status_code=404, detail='Snapshot not found')
            baseline_snap = dict(baseline_row)
            current_snap = dict(current_row)
    finally:
        conn.close()

    baseline_content = _read_config_file(baseline_snap['file_path']) if baseline_snap.get('file_path') else ''
    current_content = _read_config_file(current_snap['file_path']) if current_snap.get('file_path') else ''

    diff_result = _compute_diff(baseline_content, current_content)

    return {
        'device_id': device_id,
        'hostname': current_snap.get('hostname', ''),
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
            SELECT id, hostname, vendor, timestamp, trigger, author, tag, size
            FROM config_snapshots
            WHERE device_id = ?
            ORDER BY timestamp DESC
        ''', (device_id,)).fetchall()
        return [dict(r) for r in rows]
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

    if not body.selected_lines:
        # Full rollback — return the entire baseline config
        return {
            'mode': 'full',
            'commands': baseline_content.splitlines(),
            'line_count': len(baseline_content.splitlines()),
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

    return {
        'mode': 'selective',
        'commands': all_add_lines,
        'line_count': len(all_add_lines),
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
