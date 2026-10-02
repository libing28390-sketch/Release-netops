"""Durable, two-phase synchronization for credential password changes."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.crypto import decrypt_credential, encrypt_credential
from database import get_db_connection
from services import credential_service
from services.job_service import add_job_event, complete_target, create_job, get_job
from services.vault_service import resolve_device_credentials

logger = logging.getLogger(__name__)

_TERMINAL_JOB_STATUSES = {'succeeded', 'partially_failed', 'failed', 'cancelled', 'timeout'}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_device_snapshot(device: dict[str, Any]) -> dict[str, Any]:
    return {
        key: device.get(key)
        for key in (
            'id', 'hostname', 'ip_address', 'platform', 'vendor', 'asset_id',
            'asset_type', 'management_port', 'ssh_port', 'auth_model',
            'normal_username', 'admin_username', 'username', 'site_id',
        )
        if device.get(key) is not None
    }


def _load_sync(conn, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM credential_password_sync_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    if not row:
        raise ValueError(f'Credential sync job not found: {job_id}')
    return dict(row)


def _update_sync_status(job_id: str, status: str, *, central_status: str | None = None) -> None:
    conn = get_db_connection()
    try:
        fields = ['status = ?', 'updated_at = ?']
        params: list[Any] = [status, _now()]
        if central_status is not None:
            fields.append('central_commit_status = ?')
            params.append(central_status)
        params.append(job_id)
        conn.execute(
            f"UPDATE credential_password_sync_jobs SET {', '.join(fields)} WHERE job_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def _release_lock(conn, credential_id: str, job_id: str) -> None:
    conn.execute(
        "DELETE FROM credential_password_sync_locks WHERE credential_id = ? AND job_id = ?",
        (credential_id, job_id),
    )


def _acquire_lock(conn, credential_id: str, job_id: str) -> None:
    existing = conn.execute(
        "SELECT job_id FROM credential_password_sync_locks WHERE credential_id = ?",
        (credential_id,),
    ).fetchone()
    if existing:
        old_job_id = existing['job_id']
        if old_job_id == job_id:
            return
        old_job = conn.execute("SELECT status FROM jobs WHERE id = ?", (old_job_id,)).fetchone()
        if old_job and old_job['status'] not in _TERMINAL_JOB_STATUSES:
            raise ValueError(f'Credential already has a running password sync job: {old_job_id}')
        _release_lock(conn, credential_id, old_job_id)
    conn.execute(
        "INSERT INTO credential_password_sync_locks (credential_id, job_id, created_at) VALUES (?, ?, ?)",
        (credential_id, job_id, _now()),
    )


def _target_role(device: dict[str, Any], credential_id: str) -> str:
    return 'admin' if str(device.get('admin_credential_id') or '') == str(credential_id) else 'normal'


def create_password_sync_job(
    conn,
    *,
    credential_id: str,
    new_password: str | None,
    new_enable_password: str | None,
    old_password: str | None,
    old_enable_password: str | None,
    actor_username: str | None,
) -> dict[str, Any]:
    """Validate and persist a password sync job without changing the vault."""
    if not credential_id or (new_password is None and new_enable_password is None):
        raise ValueError('At least one new password is required')

    credential_service.validate_secret_change_confirmation(
        conn,
        credential_id,
        old_password=old_password,
        old_enable_password=old_enable_password,
        new_password=new_password,
        new_enable_password=new_enable_password,
    )
    device_rows = conn.execute(
        """
        SELECT * FROM devices
        WHERE credential_id = ? OR admin_credential_id = ?
        ORDER BY hostname, id
        """,
        (credential_id, credential_id),
    ).fetchall()
    devices = [dict(row) for row in device_rows]
    if not devices:
        return {'job_id': None, 'device_count': 0, 'credential': credential_service.get_credential(conn, credential_id)}

    job_id = f"job-{uuid.uuid4().hex[:12]}"
    lock_conn = get_db_connection()
    try:
        _acquire_lock(lock_conn, credential_id, job_id)
        lock_conn.commit()
    except Exception:
        lock_conn.rollback()
        lock_conn.close()
        raise
    try:
        lock_conn.close()
    except Exception:
        pass

    try:
        job = create_job(
            job_id=job_id,
            job_type='credential_password_sync',
            task_name=f'Credential password synchronization: {credential_id}',
            created_by=actor_username or 'system',
            targets=[
                {
                    'target_id': device['id'],
                    'target_type': 'device',
                    'site_id': device.get('site_id'),
                    'vendor': device.get('vendor'),
                }
                for device in devices
            ],
            steps=['preflight', 'hardware_change', 'verify', 'central_commit'],
            concurrency_limit=max(1, min(int(settings.PASSWORD_SYNC_MAX_WORKERS), 20)),
            retry_limit=max(0, int(settings.PASSWORD_SYNC_RETRY_LIMIT)),
            timeout_seconds=max(60, int(settings.PASSWORD_SYNC_DEVICE_TIMEOUT_SECONDS)),
            scope={'credential_id': credential_id, 'sync_type': 'credential_password'},
        )
        job_targets = {str(item['target_id']): item for item in job['targets']}
        sync_conn = get_db_connection()
        try:
            sync_conn.execute(
                """
                INSERT INTO credential_password_sync_jobs
                    (job_id, credential_id, new_password, new_enable_password,
                     actor_username, status, central_commit_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'queued', 'pending', ?, ?)
                """,
                (
                    job_id,
                    credential_id,
                    encrypt_credential(new_password) if new_password is not None else '',
                    encrypt_credential(new_enable_password) if new_enable_password is not None else '',
                    actor_username or 'system',
                    _now(),
                    _now(),
                ),
            )
            for device in devices:
                target = job_targets[str(device['id'])]
                resolved = resolve_device_credentials(device)
                role = _target_role(device, credential_id)
                target_username = (
                    resolved.get('admin_username') or device.get('admin_username') or device.get('username')
                    if role == 'admin'
                    else resolved.get('normal_username') or device.get('normal_username') or 'user'
                )
                target_password = (
                    resolved.get('admin_password') or resolved.get('password')
                    if role == 'admin'
                    else resolved.get('normal_password') or resolved.get('password')
                )
                admin_username = resolved.get('admin_username') or resolved.get('username') or device.get('username')
                admin_password = resolved.get('admin_password') or resolved.get('password')
                if not target_username or not target_password or not admin_username or not admin_password:
                    raise ValueError(f"Device {device.get('hostname') or device['id']} lacks a complete management credential")
                sync_conn.execute(
                    """
                    INSERT INTO credential_password_sync_targets
                        (job_target_id, job_id, device_id, role, target_username,
                         old_target_password, old_admin_username, old_admin_password,
                         old_enable_password, device_snapshot_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target['id'], job_id, device['id'], role, target_username,
                        encrypt_credential(target_password) or '',
                        admin_username,
                        encrypt_credential(admin_password) or '',
                        encrypt_credential(resolved.get('enable_password') or '') or '',
                        json.dumps(_safe_device_snapshot(device), ensure_ascii=True),
                    ),
                )
            sync_conn.commit()
        except Exception:
            sync_conn.rollback()
            raise
        finally:
            sync_conn.close()
        return {'job_id': job_id, 'device_count': len(devices), 'job': job}
    except Exception:
        cleanup = get_db_connection()
        try:
            cleanup.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            _release_lock(cleanup, credential_id, job_id)
            cleanup.commit()
        finally:
            cleanup.close()
        raise


def _load_target_snapshot(job_target_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    conn = get_db_connection()
    try:
        target = conn.execute(
            "SELECT * FROM credential_password_sync_targets WHERE job_target_id = ?",
            (job_target_id,),
        ).fetchone()
        if not target:
            raise ValueError(f'Credential sync target not found: {job_target_id}')
        sync = _load_sync(conn, target['job_id'])
        return dict(target), sync
    finally:
        conn.close()


def _plain_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'normal_username': row.get('target_username') if row.get('role') == 'normal' else '',
        'admin_username': row.get('old_admin_username') or '',
        'username': row.get('old_admin_username') or '',
        'normal_password': decrypt_credential(row.get('old_target_password') or '') if row.get('role') == 'normal' else '',
        'admin_password': decrypt_credential(row.get('old_target_password') or '') if row.get('role') == 'admin' else decrypt_credential(row.get('old_admin_password') or ''),
        'password': decrypt_credential(row.get('old_admin_password') or ''),
        'enable_password': decrypt_credential(row.get('old_enable_password') or ''),
    }


def _rotate_one_role(
    device_id: str,
    *,
    role: str,
    new_password: str,
    creds: dict[str, Any],
    sync: dict[str, Any],
) -> dict[str, Any]:
    from services.password_rotation_service import rotate_password

    return rotate_password(
        device_id,
        role=role,
        target_password=new_password,
        credential_snapshot=creds,
        sync_vault=False,
        connection_timeout=int(settings.PASSWORD_SYNC_CONNECT_TIMEOUT_SECONDS),
        command_read_timeout=int(settings.PASSWORD_SYNC_COMMAND_READ_TIMEOUT_SECONDS),
    )


def _rollback_one_role(
    device_id: str,
    *,
    role: str,
    old_password: str,
    new_password: str,
    creds: dict[str, Any],
    sync: dict[str, Any],
) -> dict[str, Any]:
    from services.password_rotation_service import rotate_password

    login_username = None
    login_password = None
    if role == 'admin':
        login_username = creds.get('admin_username') or creds.get('username')
        login_password = new_password
    return rotate_password(
        device_id,
        role=role,
        target_password=old_password,
        credential_snapshot=creds,
        login_username=login_username,
        login_password=login_password,
        sync_vault=False,
        connection_timeout=int(settings.PASSWORD_SYNC_CONNECT_TIMEOUT_SECONDS),
        command_read_timeout=int(settings.PASSWORD_SYNC_COMMAND_READ_TIMEOUT_SECONDS),
    )


def execute_credential_sync_target(job_target_id: str) -> dict[str, Any]:
    """Execute one target; called by the unified job worker."""
    target, sync = _load_target_snapshot(job_target_id)
    device_id = target['device_id']
    creds = _plain_snapshot(target)
    new_password = decrypt_credential(sync.get('new_password') or '') if sync.get('new_password') else None
    new_enable_password = decrypt_credential(sync.get('new_enable_password') or '') if sync.get('new_enable_password') else None
    changed: list[dict[str, str]] = []

    def fail(message: str) -> None:
        for item in reversed(changed):
            rollback = _rollback_one_role(
                device_id,
                role=item['role'],
                old_password=item['old_password'],
                new_password=item['new_password'],
                creds=creds,
                sync=sync,
            )
            if not rollback.get('success'):
                raise RuntimeError(f'{message}; rollback failed for role {item["role"]}')
        raise RuntimeError(message + ('; local changes rolled back' if changed else ''))

    # Enable is intentionally applied first, so a later login-password failure
    # can still be rolled back with the old management credential.
    if new_enable_password is not None:
        result = _rotate_one_role(device_id, role='enable', new_password=new_enable_password, creds=creds, sync=sync)
        if not result.get('success'):
            fail('Enable password change failed')
        changed.append({'role': 'enable', 'old_password': creds.get('enable_password') or '', 'new_password': new_enable_password})

    if new_password is not None:
        role = target['role']
        old_password = creds.get('admin_password') if role == 'admin' else creds.get('normal_password')
        result = _rotate_one_role(device_id, role=role, new_password=new_password, creds=creds, sync=sync)
        if not result.get('success'):
            fail(f'{role} password change failed')
        changed.append({'role': role, 'old_password': old_password or '', 'new_password': new_password})

    return {'success': True, 'device_id': device_id, 'changed_roles': [item['role'] for item in changed]}


def _rollback_completed_targets(job: dict[str, Any]) -> bool:
    all_ok = True
    for target in job.get('targets', []):
        if target.get('status') != 'succeeded':
            continue
        try:
            result = json.loads(target.get('result_json') or '{}')
        except Exception:
            result = {}
        if not result.get('changed_roles'):
            continue
        snapshot, sync = _load_target_snapshot(target['id'])
        creds = _plain_snapshot(snapshot)
        new_password = decrypt_credential(sync.get('new_password') or '') if sync.get('new_password') else None
        new_enable_password = decrypt_credential(sync.get('new_enable_password') or '') if sync.get('new_enable_password') else None
        role_passwords = {
            'enable': (creds.get('enable_password') or '', new_enable_password or ''),
            'normal': (creds.get('normal_password') or '', new_password or ''),
            'admin': (creds.get('admin_password') or '', new_password or ''),
        }
        rollback_results = []
        for role in reversed(result['changed_roles']):
            old_value, new_value = role_passwords[role]
            rollback = _rollback_one_role(
                snapshot['device_id'], role=role, old_password=old_value,
                new_password=new_value, creds=creds, sync=sync,
            )
            rollback_results.append({'role': role, 'success': bool(rollback.get('success'))})
            if not rollback.get('success'):
                all_ok = False
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE job_targets SET status = 'failed', result_json = ?, error_message = ? WHERE id = ?",
                (json.dumps({'changed_roles': result['changed_roles'], 'rollback': rollback_results}, ensure_ascii=True),
                 'Hardware synchronization failed; rollback attempted', target['id']),
            )
            conn.commit()
        finally:
            conn.close()
    return all_ok


def run_credential_password_sync_job(job_id: str) -> dict[str, Any]:
    """Run the durable job and commit the vault only after all targets pass."""
    lock_conn = get_db_connection()
    try:
        sync_for_lock = _load_sync(lock_conn, job_id)
        _acquire_lock(lock_conn, sync_for_lock['credential_id'], job_id)
        lock_conn.commit()
    finally:
        lock_conn.close()
    _update_sync_status(job_id, 'preflight')
    job = get_job(job_id)
    conn = get_db_connection()
    try:
        sync = _load_sync(conn, job_id)
        target_rows = conn.execute(
            "SELECT * FROM credential_password_sync_targets WHERE job_id = ?", (job_id,)
        ).fetchall()
    finally:
        conn.close()
    if not target_rows:
        _update_sync_status(job_id, 'failed', central_status='blocked')
        cleanup = get_db_connection()
        try:
            _release_lock(cleanup, sync['credential_id'], job_id)
            cleanup.commit()
        finally:
            cleanup.close()
        return get_job(job_id)

    # All snapshots are validated before the first hardware change.
    preflight_failures = []
    for row in target_rows:
        snapshot = dict(row)
        if not snapshot.get('old_admin_username') or not snapshot.get('old_admin_password'):
            preflight_failures.append((row['job_target_id'], 'Missing privileged login credential'))
        if not snapshot.get('device_snapshot_json'):
            preflight_failures.append((row['job_target_id'], 'Missing device snapshot'))
    for target_id, message in preflight_failures:
        complete_target(target_id, status='failed', error_message=message)
    if preflight_failures:
        _update_sync_status(job_id, 'failed', central_status='blocked')
        cleanup = get_db_connection()
        try:
            _release_lock(cleanup, sync['credential_id'], job_id)
            cleanup.commit()
        finally:
            cleanup.close()
        return get_job(job_id)

    _update_sync_status(job_id, 'running')
    from services.job_worker import run_job
    job = run_job(job_id)
    if job.get('status') == 'succeeded':
        conn = get_db_connection()
        try:
            sync = _load_sync(conn, job_id)
            updates: dict[str, Any] = {}
            new_password = decrypt_credential(sync.get('new_password') or '') if sync.get('new_password') else None
            new_enable_password = decrypt_credential(sync.get('new_enable_password') or '') if sync.get('new_enable_password') else None
            if new_password is not None:
                updates['password'] = new_password
            if new_enable_password is not None:
                updates['enable_password'] = new_enable_password
            credential_service.update_credential(conn, sync['credential_id'], **updates)
            conn.execute(
                "UPDATE credential_password_sync_jobs SET status = 'succeeded', central_commit_status = 'committed', central_committed_at = ?, updated_at = ? WHERE job_id = ?",
                (_now(), _now(), job_id),
            )
            add_job_event(conn, job_id, 'central_commit', 'Credential vault updated after all device verifications succeeded')
            _release_lock(conn, sync['credential_id'], job_id)
            conn.commit()
        except Exception:
            conn.rollback()
            _update_sync_status(job_id, 'manual_intervention', central_status='commit_failed')
            cleanup = get_db_connection()
            try:
                _release_lock(cleanup, sync['credential_id'], job_id)
                cleanup.commit()
            finally:
                cleanup.close()
            raise
        finally:
            conn.close()
        return get_job(job_id)

    rollback_ok = _rollback_completed_targets(job)
    conn = get_db_connection()
    try:
        sync = _load_sync(conn, job_id)
        status = 'failed' if rollback_ok else 'manual_intervention'
        central_status = 'unchanged' if rollback_ok else 'manual_intervention'
        conn.execute(
            "UPDATE credential_password_sync_jobs SET status = ?, central_commit_status = ?, updated_at = ? WHERE job_id = ?",
            (status, central_status, _now(), job_id),
        )
        _release_lock(conn, sync['credential_id'], job_id)
        add_job_event(conn, job_id, 'rollback_completed', 'Device rollback completed' if rollback_ok else 'Device rollback requires manual intervention', severity='warning' if rollback_ok else 'error')
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)
