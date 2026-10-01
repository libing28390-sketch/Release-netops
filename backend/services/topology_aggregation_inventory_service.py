"""Persist complete, current SNMP LAG snapshots without opening a CLI session."""

from __future__ import annotations

import math
import re
import uuid
from typing import Any

from core.interface_utils import normalize_interface_name
from database import get_db_connection


def _speed_bps(value: Any) -> float | None:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return None
    return speed * 1_000_000 if math.isfinite(speed) and speed > 0 else None


def persist_snmp_aggregation_inventory(
    device: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    snapshot_generation: int,
) -> dict[str, Any]:
    """Replace membership only after a complete walk and a current generation.

    Interface aliases reuse existing rows. Transport failures, unsupported
    tables and an obsolete discovery never detach the last valid inventory.
    Missing operational status stays unknown; absent speed preserves CMDB speed.
    """
    summary = {
        'status': str(snapshot.get('status') or 'unavailable'),
        'source': 'snmp', 'parents': 0, 'members': 0,
        'membership_source': str(snapshot.get('membership_source') or ''),
    }
    if snapshot.get('detail'):
        summary['detail'] = snapshot['detail']
    if summary['status'] != 'success':
        return summary

    device_id = str(device.get('id') or '')
    if not device_id or snapshot_generation <= 0:
        return {**summary, 'status': 'superseded'}
    parents = list(snapshot.get('parents') or [])
    records = list(snapshot.get('records') or [])
    parent_keys = {
        normalize_interface_name(parent.get('interface_name')).lower()
        for parent in parents
    }
    if '' in parent_keys or len(parent_keys) != len(parents) or any(
        not normalize_interface_name(record.get('member_interface'))
        or normalize_interface_name(record.get('aggregation_name')).lower() not in parent_keys
        for record in records
    ):
        return {**summary, 'status': 'partial', 'detail': 'invalid_aggregation_snapshot'}

    conn = get_db_connection()
    try:
        marker = conn.execute(
            'SELECT generation, state FROM topology_device_lldp_snapshots WHERE device_id = ? FOR UPDATE',
            (device_id,),
        ).fetchone()
        if marker is None or int(marker['generation']) != snapshot_generation or marker['state'] != 'collecting':
            conn.rollback()
            return {**summary, 'status': 'superseded'}
        current_device = conn.execute(
            'SELECT ip_address FROM devices WHERE id = ? FOR UPDATE', (device_id,),
        ).fetchone()
        if current_device is None or str(current_device['ip_address'] or '') != str(device.get('ip_address') or ''):
            conn.rollback()
            return {**summary, 'status': 'superseded'}
        rows = [dict(row) for row in conn.execute(
            'SELECT id, interface_name, interface_type, if_index FROM interfaces WHERE device_id = ? FOR UPDATE',
            (device_id,),
        ).fetchall()]
        by_key: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_key.setdefault(normalize_interface_name(row['interface_name']).lower(), []).append(row)

        def choose_row(name: str, if_index: Any) -> dict[str, Any] | None:
            candidates = by_key.get(normalize_interface_name(name).lower(), [])
            if len(candidates) <= 1:
                return candidates[0] if candidates else None
            indexed = [row for row in candidates if row.get('if_index') == if_index]
            if len(indexed) == 1:
                return indexed[0]
            exact = [row for row in candidates if row['interface_name'] == name]
            if len(exact) == 1:
                return exact[0]
            raise ValueError('ambiguous_interface_alias')

        # Resolve every alias before detaching anything. A failed transaction
        # must leave the previous complete snapshot intact.
        parent_rows = {
            normalize_interface_name(parent['interface_name']).lower(): choose_row(parent['interface_name'], parent.get('if_index'))
            for parent in parents
        }
        member_rows = {
            normalize_interface_name(record['member_interface']).lower(): choose_row(record['member_interface'], record.get('member_if_index'))
            for record in records
        }
        from services.topology_service import _is_logical_aggregation_interface

        logical_ids = sorted({str(row['id']) for row in rows if _is_logical_aggregation_interface(row)} | {
            str(row['id']) for row in parent_rows.values() if row is not None
        })
        # channel_group is specifically LAG membership. Other interface
        # hierarchies (for example subinterfaces) keep their parent bindings.
        if logical_ids:
            placeholders = ','.join('?' for _ in logical_ids)
            conn.execute(
                f'''UPDATE interfaces SET parent_interface_id = NULL, channel_group = NULL, aggregation_protocol = ''
                    WHERE device_id = ? AND (channel_group IS NOT NULL OR parent_interface_id IN ({placeholders}))''',
                [device_id, *logical_ids],
            )
        else:
            conn.execute(
                "UPDATE interfaces SET parent_interface_id = NULL, channel_group = NULL, aggregation_protocol = '' WHERE device_id = ? AND channel_group IS NOT NULL",
                (device_id,),
            )

        def upsert_interface(name: str, if_index: Any, kind: str, oper_status: Any, speed_mbps: Any, existing: Any) -> str:
            interface_id = str(existing['id']) if existing else str(uuid.uuid4())
            state = str(oper_status or '').lower()
            state = state if state in {'up', 'down', 'testing', 'unknown', 'dormant', 'notpresent', 'lowerlayerdown'} else 'unknown'
            speed = _speed_bps(speed_mbps)
            if existing:
                conn.execute(
                    '''UPDATE interfaces SET interface_type = ?, if_index = ?, oper_status = ?,
                           speed = COALESCE(?, speed), aggregation_protocol = '' WHERE id = ?''',
                    (kind, if_index, state, speed, interface_id),
                )
            else:
                conn.execute(
                    '''INSERT INTO interfaces (id, device_id, interface_name, interface_type, if_index, admin_status, oper_status, speed)
                       VALUES (?, ?, ?, ?, ?, 'unknown', ?, ?)''',
                    (interface_id, device_id, name, kind, if_index, state, speed or 0),
                )
            return interface_id

        parent_ids: dict[str, str] = {}
        for parent in parents:
            name = parent['interface_name']
            key = normalize_interface_name(name).lower()
            parent_ids[key] = upsert_interface(
                name, parent.get('if_index'), 'port_channel', parent.get('oper_status'), parent.get('speed_mbps'), parent_rows[key],
            )
        for record in records:
            name = record['member_interface']
            key = normalize_interface_name(name).lower()
            interface_id = upsert_interface(
                name, record.get('member_if_index'), 'physical', record.get('member_oper_status'),
                record.get('member_speed_mbps'), member_rows[key],
            )
            parent_name = record['aggregation_name']
            channel = re.search(r'(\d+)$', parent_name)
            conn.execute(
                '''UPDATE interfaces SET parent_interface_id = ?, channel_group = ?, aggregation_protocol = '' WHERE id = ?''',
                (parent_ids[normalize_interface_name(parent_name).lower()], int(channel.group(1)) if channel else None, interface_id),
            )
        conn.commit()
    except ValueError:
        conn.rollback()
        return {**summary, 'status': 'partial', 'detail': 'ambiguous_interface_alias'}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {**summary, 'parents': len(parents), 'members': len(records)}


async def sync_snmp_aggregation_inventory(
    device: dict[str, Any], collector_credentials: dict[str, Any], *, snapshot_generation: int,
) -> dict[str, Any]:
    import asyncio
    from services.topology_snmp_aggregation_service import collect_snmp_aggregation_inventory

    snapshot = await collect_snmp_aggregation_inventory(device, collector_credentials)
    return await asyncio.to_thread(
        persist_snmp_aggregation_inventory, device, snapshot, snapshot_generation=snapshot_generation,
    )
