"""Read-only diagnostics for the monitoring collection path."""

from __future__ import annotations

import asyncio
import socket
import time
from typing import Any

from database import get_db_connection
from services.collection_status_service import record_collection_result
from services.snmp_service import SYS_UPTIME, _snmp_get
from services.vault_service import resolve_collector_credentials


async def _tcp_probe(host: str, port: int, timeout: float) -> tuple[str, str]:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return 'success', f'{(time.perf_counter() - started) * 1000:.0f}'
    except asyncio.TimeoutError:
        return 'timeout', f'{(time.perf_counter() - started) * 1000:.0f}'
    except OSError as exc:
        return f'error:{type(exc).__name__}', f'{(time.perf_counter() - started) * 1000:.0f}'


def _dns_probe(host: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, None)})
        return {
            'status': 'success',
            'code': 'dns_resolved',
            'addresses': addresses[:10],
            'duration_ms': round((time.perf_counter() - started) * 1000, 1),
        }
    except OSError as exc:
        return {
            'status': 'failed',
            'code': 'dns_resolution_failed',
            'error': str(exc)[:160],
            'duration_ms': round((time.perf_counter() - started) * 1000, 1),
        }


async def diagnose_device_collection(device_id: str, timeout_seconds: float = 2.0) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''
            SELECT id, hostname, ip_address, management_port, snmp_port, snmp_credential_id,
                   username, password, credential_id, credential_source, asset_id, snmp_community
            FROM devices WHERE id = ?
            ''',
            (device_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None

    device = dict(row)
    collector_credentials = resolve_collector_credentials(device, ssh_role='normal')
    ssh_credentials = collector_credentials['ssh']
    snmp_credentials = collector_credentials['snmp']
    host = str(device.get('ip_address') or '').strip()
    snmp_host = str(snmp_credentials.get('server') or host).strip()
    management_port = int(ssh_credentials['port'])
    snmp_port = int(snmp_credentials['port'])
    result: dict[str, Any] = {
        'device_id': device_id,
        'hostname': device.get('hostname') or '',
        'ip_address': host,
        'checks': {},
    }

    if not host:
        result['checks']['dns'] = {'status': 'failed', 'code': 'ip_not_configured'}
        result['checks']['ssh_tcp'] = {'status': 'skipped', 'code': 'ip_not_configured'}
        result['checks']['snmp_udp'] = {'status': 'skipped', 'code': 'ip_not_configured'}
        return result

    result['checks']['dns'] = _dns_probe(host)
    tcp_status, tcp_duration = await _tcp_probe(host, management_port, timeout_seconds)
    result['checks']['ssh_tcp'] = {
        'status': 'success' if tcp_status == 'success' else 'failed',
        'code': 'tcp_connected' if tcp_status == 'success' else 'tcp_unreachable',
        'transport_status': tcp_status,
        'port': management_port,
        'duration_ms': float(tcp_duration),
        'credential_configured': bool(ssh_credentials.get('username') and ssh_credentials.get('password')),
    }

    community = str(snmp_credentials.get('community') or '').strip()
    if not community:
        result['checks']['snmp_udp'] = {
            'status': 'not_configured',
            'code': 'snmp_credential_missing',
            'port': snmp_port,
        }
    else:
        started = time.perf_counter()
        try:
            uptime = await asyncio.wait_for(_snmp_get(snmp_host, community, SYS_UPTIME, snmp_port, timeout=timeout_seconds), timeout=timeout_seconds + 0.5)
            result['checks']['snmp_udp'] = {
                'status': 'success' if uptime is not None else 'failed',
                'code': 'snmp_response' if uptime is not None else 'snmp_no_response',
                'port': snmp_port,
                'duration_ms': round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as exc:  # noqa: BLE001
            result['checks']['snmp_udp'] = {
                'status': 'failed',
                'code': 'snmp_probe_error',
                'port': snmp_port,
                'error': str(exc)[:160],
                'duration_ms': round((time.perf_counter() - started) * 1000, 1),
            }

    failed = [item for item in result['checks'].values() if item.get('status') == 'failed']
    result['status'] = 'failed' if failed else 'success'
    record_collection_result(
        device_id,
        'diagnostics',
        status='failed' if failed else 'success',
        transport='dns_tcp_udp161',
        source='on_demand_diagnostic',
        duration_ms=0,
        error_code=failed[0].get('code', '') if failed else '',
        error_message=failed[0].get('error', '') if failed else '',
        metadata={'checks': {key: value.get('status') for key, value in result['checks'].items()}},
    )
    return result
