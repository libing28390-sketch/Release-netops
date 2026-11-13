"""Process-safe worker loops for leased collector tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database import _USE_PG, get_db_connection
from services.collection_status_service import record_collection_results
from services.collector_task_queue_service import (
    claim_task,
    ensure_worker_slots,
    finish_task,
)

logger = logging.getLogger(__name__)

ARP_WORKERS_PER_PROCESS = max(1, int(os.environ.get('ARP_WORKERS_PER_PROCESS', '2')))
ARP_GLOBAL_WORKER_SLOTS = max(1, int(os.environ.get('ARP_GLOBAL_WORKER_SLOTS', '20')))
ARP_TASK_LEASE_SECONDS = max(60, int(os.environ.get('ARP_TASK_LEASE_SECONDS', '900')))
ARP_TASK_POLL_SECONDS = max(0.2, float(os.environ.get('ARP_TASK_POLL_SECONDS', '1')))


def _worker_id(index: int) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{index}:{uuid.uuid4().hex[:8]}"


def _load_device(device_id: str) -> dict[str, Any] | None:
    from services import ip_locator_service as locator

    conn = get_db_connection()
    try:
        placeholder = '%s' if _USE_PG else '?'
        row = conn.execute(
            f"SELECT * FROM devices WHERE id = {placeholder} AND status = 'online'",
            (device_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    device = dict(row)
    platform = str(device.get('platform') or '').lower()
    if platform in locator._ARP_UNSUPPORTED_PLATFORMS:
        return None
    creds = locator.resolve_device_credentials(device)
    attempts = locator._credential_attempts(creds, (device.get('auth_model') or 'single').lower())
    if not attempts:
        return None
    device['_ssh_username'], device['_ssh_password'] = attempts[0]
    device['_ssh_fallback_credentials'] = attempts[1:]
    device['_ssh_enable'] = creds.get('enable_password') or ''
    return device


def _retry_at(failure_class: str, attempt: int) -> datetime:
    from services import ip_locator_service as locator

    return datetime.now(timezone.utc) + timedelta(
        seconds=locator._arp_retry_delay(failure_class, max(1, attempt))
    )


def run_arp_worker_once(worker_id: str) -> bool:
    """Claim and process one ARP task; return whether a task was claimed."""
    from services import ip_locator_service as locator

    task = claim_task(
        'arp',
        worker_id=worker_id,
        slot_count=ARP_GLOBAL_WORKER_SLOTS,
        lease_seconds=ARP_TASK_LEASE_SECONDS,
    )
    if not task:
        return False

    task_id = str(task.get('id') or '')
    device_id = str(task.get('device_id') or '')
    run_id = str(task.get('run_id') or '')
    attempt = int(task.get('attempt') or 1)
    device = _load_device(device_id)
    failure_class = ''
    error_message = ''
    entries: list[dict[str, Any]] = []
    result_payload: dict[str, Any] = {'run_id': run_id, 'device_id': device_id}
    success = False
    retry_at = None
    try:
        if not device:
            raise RuntimeError('device is offline, missing credentials, or unsupported')
        try:
            payload = json.loads(task.get('payload_json') or '{}')
        except (TypeError, ValueError):
            payload = {}
        if payload.get('arp_policy_override'):
            device['_arp_policy_override'] = True
        result = locator._collect_full_arp_result(device)
        entries = result.get('entries') or []
        if result.get('status') != 'success':
            failure_class = result.get('failure_class') or 'collection_failed'
            error_message = result.get('error_message') or 'ARP collection failed'
        else:
            persisted = locator._persist_arp_device_entries(device, entries)
            result_payload.update(persisted)
            success = True
    except Exception as exc:
        failure_class = failure_class or locator._classify_arp_failure(exc)
        error_message = error_message or str(exc)

    if not success:
        retry_at = _retry_at(failure_class, attempt)
    result_payload['entry_count'] = len(entries)
    result_payload['failure_class'] = failure_class
    status_updates = [{
        'device_id': device_id,
        'collector': 'arp',
        'status': 'success' if success else 'failed',
        'transport': 'ssh',
        'source': 'arp_worker',
        'coverage_total': len(entries),
        'coverage_supported': 1 if success else 0,
        'error_code': failure_class,
        'error_message': error_message,
        'next_retry_at': retry_at.replace(microsecond=0).isoformat() if retry_at else None,
        'failure_class': failure_class,
        'circuit_state': 'closed' if success else ('open' if attempt >= 5 else 'backoff'),
        'metadata': {
            'collection_run_id': run_id,
            'worker_id': worker_id,
            'entry_count': len(entries),
            'attempt': attempt,
        },
    }]
    record_collection_results(status_updates)
    finish_task(
        task,
        worker_id=worker_id,
        success=success,
        retry_at=retry_at,
        error_class=failure_class,
        error_message=error_message,
        result=result_payload,
    )
    return True


async def _arp_worker_loop(worker_id: str) -> None:
    while True:
        claimed = await asyncio.to_thread(run_arp_worker_once, worker_id)
        if not claimed:
            await asyncio.sleep(ARP_TASK_POLL_SECONDS)


async def start_arp_worker_tasks() -> list[asyncio.Task]:
    """Start per-process consumers; DB slots enforce a global cap."""
    await asyncio.to_thread(ensure_worker_slots, 'arp', ARP_GLOBAL_WORKER_SLOTS)
    return [
        asyncio.create_task(_arp_worker_loop(_worker_id(index)), name=f'arp-worker-{index}')
        for index in range(ARP_WORKERS_PER_PROCESS)
    ]


async def stop_worker_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
