"""Explicit mappings from a device's local routing contexts to IPAM spaces."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.audit_service import log_audit_event


_DEFAULT_TENANT_ID = 'tenant-default'
_ROUTING_CONTEXT_SELECT = """
    SELECT context.id, context.device_id, device.hostname AS device_name,
           context.context_source, context.context_type,
           context.local_context_key, context.local_context_name,
           context.address_space_id, space.name AS address_space_name,
           space.kind AS address_space_kind, space.vrf_id,
           context.status, context.revision, context.last_verified_at,
           context.created_at, context.updated_at,
           COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS _security_tenant_id,
           space.security_tenant_id AS _address_space_tenant_id,
           device.site_id AS _site_id
      FROM ipam_device_routing_contexts context
      JOIN devices device ON device.id = context.device_id
      JOIN ipam_address_spaces space ON space.id = context.address_space_id
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant_key(value: object) -> str:
    return str(value or '').strip() or _DEFAULT_TENANT_ID


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _load_context(conn, context_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    sql = _ROUTING_CONTEXT_SELECT + ' WHERE context.id = ?'
    if lock:
        sql += ' FOR UPDATE OF context'
    return _row_dict(conn.execute(sql, (context_id,)).fetchone())


def get_routing_context_device_scope(device_id: str) -> dict[str, str | None] | None:
    """Return the device's tenant/site scope for the router's RBAC check."""
    normalized_device_id = str(device_id or '').strip()
    if not normalized_device_id:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT COALESCE(NULLIF(btrim(tenant_id), ''), 'tenant-default') AS tenant_id,
                      site_id
                 FROM devices
                WHERE id = ?""",
            (normalized_device_id,),
        ).fetchone()
        if not row:
            return None
        return {'tenant_id': str(row['tenant_id'] or _DEFAULT_TENANT_ID), 'site_id': row['site_id']}
    finally:
        conn.close()


def get_routing_context_scope(context_id: str) -> dict[str, str | None] | None:
    """Return the mapped device's tenant/site scope for update authorization."""
    normalized_id = str(context_id or '').strip()
    if not normalized_id:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS tenant_id,
                      device.site_id, context.address_space_id
                 FROM ipam_device_routing_contexts context
                 JOIN devices device ON device.id = context.device_id
                WHERE context.id = ?""",
            (normalized_id,),
        ).fetchone()
        if not row:
            return None
        return {
            'tenant_id': str(row['tenant_id'] or _DEFAULT_TENANT_ID),
            'site_id': row['site_id'],
            'address_space_id': row['address_space_id'],
        }
    finally:
        conn.close()


def list_device_routing_contexts(
    *,
    device_id: str | None = None,
    security_tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """List stored explicit mappings, optionally bounded by device and tenant."""
    sql = _ROUTING_CONTEXT_SELECT + ' WHERE 1 = 1'
    params: list[Any] = []
    if device_id:
        sql += ' AND context.device_id = ?'
        params.append(str(device_id).strip())
    if security_tenant_id is not None:
        sql += " AND COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') = ?"
        params.append(_tenant_key(security_tenant_id))
    sql += ' ORDER BY device.hostname, context.context_source, context.context_type, context.local_context_key'

    conn = get_db_connection()
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def _locked_device(conn, device_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, hostname, COALESCE(NULLIF(btrim(tenant_id), ''), 'tenant-default') AS tenant_id,
                  site_id
             FROM devices
            WHERE id = ?
            FOR UPDATE""",
        (device_id,),
    ).fetchone()
    return _row_dict(row)


def _locked_address_space(
    conn,
    address_space_id: str,
    *,
    security_tenant_id: str,
    context_type: str,
) -> dict[str, Any]:
    row = conn.execute(
        """SELECT id, security_tenant_id, name, kind, vrf_id
             FROM ipam_address_spaces
            WHERE id = ?
            FOR UPDATE""",
        (address_space_id,),
    ).fetchone()
    if not row or str(row['security_tenant_id'] or '').strip() != security_tenant_id:
        raise ValueError('Address space not found in this security tenant')
    expected_kind = 'vrf' if context_type == 'vrf' else 'global'
    if str(row['kind'] or '').strip() != expected_kind:
        raise ValueError(f'{context_type} context must map to an address space of kind {expected_kind}')
    return dict(row)


def _write_audit(
    conn,
    audit_context: dict | None,
    *,
    event_type: str,
    context: dict[str, Any],
    before: dict[str, Any] | None = None,
) -> None:
    if not audit_context:
        return
    log_audit_event(
        event_type=event_type,
        category='ipam',
        severity='info',
        status='success',
        summary=f"{event_type.rsplit('.', 1)[-1].capitalize()} routing context {context['local_context_key']} on {context['device_name']}",
        actor_id=audit_context.get('actor_id'),
        actor_username=audit_context.get('actor_username'),
        actor_role=audit_context.get('actor_role'),
        request_id=audit_context.get('request_id'),
        target_type='ipam_device_routing_context',
        target_id=context['id'],
        target_name=f"{context['device_name']}:{context['local_context_key']}",
        device_id=context['device_id'],
        before=before,
        after={
            'device_id': context['device_id'],
            'context_source': context['context_source'],
            'context_type': context['context_type'],
            'local_context_key': context['local_context_key'],
            'local_context_name': context['local_context_name'],
            'address_space_id': context['address_space_id'],
            'status': context['status'],
            'revision': context['revision'],
        },
        details={'address_space_id': context['address_space_id']},
        conn=conn,
    )


def create_device_routing_context(
    *,
    device_id: str,
    context_source: str,
    context_type: str,
    local_context_key: str,
    local_context_name: str = '',
    address_space_id: str,
    security_tenant_id: str,
    audit_context: dict | None = None,
) -> dict[str, Any]:
    """Create one explicit device-local context mapping in one transaction."""
    normalized_device_id = str(device_id or '').strip()
    normalized_source = str(context_source or '').strip().lower()
    normalized_type = str(context_type or '').strip().lower()
    normalized_key = str(local_context_key or '').strip()
    normalized_name = str(local_context_name or '').strip()
    normalized_space_id = str(address_space_id or '').strip()
    tenant_key = _tenant_key(security_tenant_id)
    if not normalized_device_id or not normalized_key or not normalized_space_id or not tenant_key:
        raise ValueError('Device, local context key, address space and security tenant are required')
    if normalized_source not in {'cli', 'snmp'}:
        raise ValueError('context_source must be cli or snmp')
    if normalized_type not in {'vrf', 'global'}:
        raise ValueError('context_type must be vrf or global')

    conn = get_db_connection()
    try:
        device = _locked_device(conn, normalized_device_id)
        if not device or str(device['tenant_id'] or '') != tenant_key:
            raise ValueError('Device not found in this security tenant')
        space = _locked_address_space(
            conn,
            normalized_space_id,
            security_tenant_id=tenant_key,
            context_type=normalized_type,
        )
        now = _utc_now()
        context_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type,
                    local_context_key, local_context_name, address_space_id,
                    status, revision, last_verified_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1, NULL, ?, ?)""",
            (
                context_id, normalized_device_id, normalized_source, normalized_type,
                normalized_key, normalized_name, normalized_space_id, now, now,
            ),
        )
        context = _load_context(conn, context_id)
        if not context:
            raise RuntimeError('Created routing-context mapping could not be loaded')
        _write_audit(
            conn,
            audit_context,
            event_type='ipam.device_routing_context.create',
            context=context,
        )
        conn.commit()
        return context
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('A mapping already exists for this device-local context') from exc
        raise
    finally:
        conn.close()


def update_device_routing_context(
    context_id: str,
    *,
    expected_revision: int,
    security_tenant_id: str,
    address_space_id: str | None = None,
    local_context_name: str | None = None,
    status: str | None = None,
    update_local_context_name: bool = False,
    update_status: bool = False,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    """Update an explicit mapping with a locked revision compare-and-swap."""
    normalized_id = str(context_id or '').strip()
    if not normalized_id:
        return None
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
        raise ValueError('expected_revision must be a positive integer')
    tenant_key = _tenant_key(security_tenant_id)
    normalized_space_id = None if address_space_id is None else str(address_space_id).strip()
    if address_space_id is not None and not normalized_space_id:
        raise ValueError('address_space_id must not be empty')
    normalized_name = None if not update_local_context_name else str(local_context_name or '').strip()
    normalized_status = None if not update_status else str(status or '').strip().lower()
    if normalized_status is not None and normalized_status not in {'active', 'disabled'}:
        raise ValueError('status must be active or disabled')
    if normalized_space_id is None and normalized_name is None and normalized_status is None:
        raise ValueError('At least one routing-context field must be updated')

    conn = get_db_connection()
    try:
        initial = _load_context(conn, normalized_id)
        if not initial:
            return None
        # Keep the device row first in the lock order shared with creation.
        # This prevents a concurrent create/update of the same device from
        # acquiring device and mapping locks in opposite orders.
        device = _locked_device(conn, str(initial['device_id']))
        if not device or str(device['tenant_id'] or '') != tenant_key:
            raise ValueError('Device not found in this security tenant')
        current = _load_context(conn, normalized_id, lock=True)
        if not current or str(current['device_id']) != str(initial['device_id']):
            return None
        if str(current['_security_tenant_id'] or '') != tenant_key:
            raise ValueError('Routing-context mapping not found in this security tenant')
        if int(current['revision'] or 0) != expected_revision:
            raise ValueError('Routing-context revision is stale; refresh and retry')

        target_space_id = normalized_space_id or str(current['address_space_id'])
        _locked_address_space(
            conn,
            target_space_id,
            security_tenant_id=tenant_key,
            context_type=str(current['context_type']),
        )

        assignments: list[str] = []
        values: list[Any] = []
        if normalized_space_id is not None:
            assignments.append('address_space_id = ?')
            values.append(normalized_space_id)
        if update_local_context_name:
            assignments.append('local_context_name = ?')
            values.append(normalized_name or '')
        if update_status:
            assignments.append('status = ?')
            values.append(normalized_status)
        now = _utc_now()
        assignments.extend(['revision = revision + 1', 'updated_at = ?'])
        values.extend([now, normalized_id, expected_revision])
        cursor = conn.execute(
            f"UPDATE ipam_device_routing_contexts SET {', '.join(assignments)} WHERE id = ? AND revision = ?",
            tuple(values),
        )
        if int(getattr(cursor, 'rowcount', 0) or 0) != 1:
            raise ValueError('Routing-context revision is stale; refresh and retry')

        updated = _load_context(conn, normalized_id)
        if not updated:
            raise RuntimeError('Updated routing-context mapping could not be loaded')
        before = {
            key: current.get(key)
            for key in (
                'device_id', 'context_source', 'context_type', 'local_context_key',
                'local_context_name', 'address_space_id', 'status', 'revision',
            )
        }
        _write_audit(
            conn,
            audit_context,
            event_type='ipam.device_routing_context.update',
            context=updated,
            before=before,
        )
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
