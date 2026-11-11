"""Explicit logical groups for IPAM FHRP and Anycast resources."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.interface_utils import normalize_interface_name
from database import get_db_connection
from services.ipam_address_space_service import lock_ipam_scope
from services.ipam_service import (
    _idempotency_replay,
    _store_idempotency_response,
    _write_ipam_audit,
)


_DEFAULT_TENANT_ID = 'tenant-default'
_GROUP_TYPES = {'fhrp', 'anycast'}
_PROTOCOLS = {'hsrp', 'vrrp', 'anycast'}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant(value: object) -> str:
    return str(value or '').strip() or _DEFAULT_TENANT_ID


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _stringify_timestamps(record: dict[str, Any], *field_names: str) -> dict[str, Any]:
    for field_name in field_names:
        if record.get(field_name) is not None:
            record[field_name] = str(record[field_name])
    return record


def _validate_group_protocol(group_type: str, protocol: str) -> None:
    normalized_type = str(group_type or '').strip().lower()
    normalized_protocol = str(protocol or '').strip().lower()
    if normalized_type not in _GROUP_TYPES or normalized_protocol not in _PROTOCOLS:
        raise ValueError('Unsupported FHRP group type or protocol')
    if normalized_type == 'fhrp' and normalized_protocol not in {'hsrp', 'vrrp'}:
        raise ValueError('FHRP groups require the HSRP or VRRP protocol')
    if normalized_type == 'anycast' and normalized_protocol != 'anycast':
        raise ValueError('Anycast groups require protocol=anycast')


def _group_select_sql(*, lock: bool = False) -> str:
    query = """
        SELECT group_row.id, group_row.security_tenant_id,
               group_row.address_space_id, space.name AS address_space_name,
               group_row.group_type, group_row.protocol, group_row.group_id,
               group_row.address_family, group_row.display_name,
               group_row.status, group_row.revision,
               group_row.created_at, group_row.updated_at,
               space.security_tenant_id AS _address_space_tenant_id
          FROM ipam_fhrp_groups group_row
          JOIN ipam_address_spaces space
            ON space.id = group_row.address_space_id
    """
    if lock:
        query += ' WHERE group_row.id = ? FOR UPDATE OF group_row'
    return query


def _load_group(conn, group_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    if lock:
        return _row_dict(conn.execute(_group_select_sql(lock=True), (group_id,)).fetchone())
    query = _group_select_sql() + ' WHERE group_row.id = ?'
    return _row_dict(conn.execute(query, (group_id,)).fetchone())


def _load_group_detail(conn, group_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    group = _load_group(conn, group_id, lock=lock)
    if not group:
        return None

    member_rows = conn.execute(
        """
        SELECT member.id, member.group_id, member.device_id,
               device.hostname AS device_name, member.interface_id,
               member.interface_name, member.normalized_interface_name,
               member.role, member.priority, member.status, member.revision,
               member.created_at, member.updated_at,
               COALESCE(NULLIF(btrim(device.tenant_id), ''), ?) AS _member_tenant_id,
               device.site_id AS _site_id
          FROM ipam_fhrp_group_members member
          JOIN devices device ON device.id = member.device_id
         WHERE member.group_id = ?
         ORDER BY member.device_id, member.normalized_interface_name, member.id
        """,
        (_DEFAULT_TENANT_ID, group_id),
    ).fetchall()
    vip_rows = conn.execute(
        """
        SELECT relation.id AS _relation_id, relation.group_id, relation.vip_id,
               COALESCE(host(vip.address_inet), vip.address) AS address,
               vip.vip_type, vip.status, vip.address_space_id,
               COALESCE(NULLIF(btrim(vip.tenant_id), ''), ?) AS tenant_id,
               vip.prefix_id, vip.revision, relation.created_at AS linked_at,
               prefix.site_id AS _site_id
          FROM ipam_fhrp_group_vips relation
          JOIN ipam_vips vip ON vip.id = relation.vip_id
          LEFT JOIN prefixes prefix ON prefix.id = vip.prefix_id
         WHERE relation.group_id = ?
         ORDER BY relation.vip_id
        """,
        (_DEFAULT_TENANT_ID, group_id),
    ).fetchall()
    group['members'] = [dict(row) for row in member_rows]
    group['vips'] = [dict(row) for row in vip_rows]
    _stringify_timestamps(group, 'created_at', 'updated_at')
    for member in group['members']:
        _stringify_timestamps(member, 'created_at', 'updated_at')
    for vip in group['vips']:
        _stringify_timestamps(vip, 'linked_at')
    return group


def _clean_replay(replay: dict | None) -> dict | None:
    if replay is None:
        return None
    replay.pop('_idempotency_replay', None)
    return replay


def _replay_or_store_result(
    conn,
    *,
    tenant_id: str,
    operation: str,
    idempotency_key: str | None,
    payload: dict,
) -> dict | None:
    replay = _idempotency_replay(
        conn,
        tenant_id=tenant_id,
        operation=operation,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        conn.commit()
        return _clean_replay(replay)
    return None


def _begin_group_write(
    conn,
    *,
    group_id: str,
    security_tenant_id: str,
    operation: str,
    idempotency_key: str | None,
    payload: dict,
) -> tuple[dict[str, Any] | None, dict | None]:
    tenant_id = _tenant(security_tenant_id)
    initial = _load_group(conn, group_id)
    if not initial:
        return None, _replay_or_store_result(
            conn,
            tenant_id=tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    if _tenant(initial['security_tenant_id']) != tenant_id:
        raise ValueError('FHRP group not found in this security tenant')

    lock_ipam_scope(
        conn,
        security_tenant_id=tenant_id,
        address_space_id=str(initial['address_space_id']),
    )
    group = _load_group(conn, group_id, lock=True)
    if not group:
        return None, _replay_or_store_result(
            conn,
            tenant_id=tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
    if _tenant(group['security_tenant_id']) != tenant_id:
        raise ValueError('FHRP group not found in this security tenant')
    replay = _replay_or_store_result(
        conn,
        tenant_id=tenant_id,
        operation=operation,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is None:
        _assert_active_space(
            conn,
            str(group['address_space_id']),
            tenant_id,
        )
    return (None, replay) if replay is not None else (group, None)


def _check_expected_revision(group: dict, expected_revision: int) -> int:
    current = int(group.get('revision') or 1)
    if current != int(expected_revision):
        raise ValueError('FHRP group revision is stale; refresh and retry')
    return current


def _advance_group_revision(conn, group_id: str, expected_revision: int, now: str) -> int:
    row = conn.execute(
        """
        UPDATE ipam_fhrp_groups
           SET revision = revision + 1, updated_at = ?
         WHERE id = ? AND revision = ?
         RETURNING revision
        """,
        (now, group_id, expected_revision),
    ).fetchone()
    if not row:
        raise ValueError('FHRP group revision is stale; refresh and retry')
    return int(row['revision'])


def _assert_active_space(conn, address_space_id: str, security_tenant_id: str) -> dict:
    row = conn.execute(
        """
        SELECT id, security_tenant_id, name, status
          FROM ipam_address_spaces
         WHERE id = ?
         FOR UPDATE
        """,
        (address_space_id,),
    ).fetchone()
    if not row:
        raise ValueError('Explicit IPAM address space not found')
    if _tenant(row['security_tenant_id']) != _tenant(security_tenant_id):
        raise ValueError('Address space does not belong to this security tenant')
    if str(row['status'] or '').strip().lower() != 'active':
        raise ValueError('FHRP groups require an active explicit address space')
    return dict(row)


def _assert_protocol_family_compatible(
    conn,
    *,
    group_id: str,
    protocol: str,
    address_family: int,
) -> None:
    rows = conn.execute(
        """
        SELECT vip.vip_type, family(vip.address_inet) AS address_family,
               vip.address_inet
          FROM ipam_fhrp_group_vips relation
          JOIN ipam_vips vip ON vip.id = relation.vip_id
         WHERE relation.group_id = ?
         FOR UPDATE OF vip
        """,
        (group_id,),
    ).fetchall()
    for vip in rows:
        if str(vip['vip_type'] or '').strip().lower() != protocol:
            raise ValueError('Existing VIP protocol does not match the target group protocol')
        if vip['address_inet'] is None or int(vip['address_family'] or 0) != int(address_family):
            raise ValueError('Existing VIP address family does not match the target group')


def list_fhrp_groups(
    *,
    security_tenant_id: str | None = None,
    address_space_id: str | None = None,
    allowed_address_space_ids: list[str] | set[str] | None = None,
    q: str = '',
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        where_clauses = ['1 = 1']
        params: list[Any] = []
        if security_tenant_id is not None:
            where_clauses.append('group_row.security_tenant_id = ?')
            params.append(_tenant(security_tenant_id))
        if address_space_id:
            where_clauses.append('group_row.address_space_id = ?')
            params.append(str(address_space_id).strip())
        if allowed_address_space_ids is not None:
            allowed_ids = sorted({str(value).strip() for value in allowed_address_space_ids if str(value).strip()})
            if allowed_ids:
                where_clauses.append(
                    f"group_row.address_space_id IN ({', '.join('?' for _ in allowed_ids)})"
                )
                params.extend(allowed_ids)
            else:
                where_clauses.append('1 = 0')
        normalized_query = str(q or '').strip().lower()
        if normalized_query:
            pattern = f'%{normalized_query}%'
            where_clauses.append(
                "(LOWER(COALESCE(group_row.group_id, '')) LIKE ? "
                "OR LOWER(COALESCE(group_row.display_name, '')) LIKE ? "
                "OR LOWER(COALESCE(space.name, '')) LIKE ?)"
            )
            params.extend((pattern, pattern, pattern))
        where_sql = f" WHERE {' AND '.join(where_clauses)}"
        count_row = conn.execute(
            """SELECT COUNT(*) AS total
                 FROM ipam_fhrp_groups group_row
                 JOIN ipam_address_spaces space ON space.id = group_row.address_space_id"""
            + where_sql,
            tuple(params),
        ).fetchone()
        total = int(count_row['total'] or 0) if count_row else 0
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        rows = conn.execute(
            _group_select_sql()
            + where_sql
            + ' ORDER BY group_row.address_space_id, group_row.protocol, group_row.group_id, group_row.id'
            + ' LIMIT ? OFFSET ?',
            tuple(params + [safe_page_size, (safe_page - 1) * safe_page_size]),
        ).fetchall()
        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': safe_page,
            'page_size': safe_page_size,
            'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size),
        }
    finally:
        conn.close()


def get_fhrp_group(group_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        return _load_group_detail(conn, str(group_id or '').strip())
    finally:
        conn.close()


def get_fhrp_group_scope(group_id: str) -> dict[str, str] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT group_row.security_tenant_id, group_row.address_space_id,
                   space.security_tenant_id AS _address_space_tenant_id
              FROM ipam_fhrp_groups group_row
              JOIN ipam_address_spaces space
                ON space.id = group_row.address_space_id
             WHERE group_row.id = ?
            """,
            (str(group_id or '').strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_fhrp_device_scope(device_id: str) -> dict[str, str | None] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(NULLIF(btrim(tenant_id), ''), ?) AS tenant_id, site_id
              FROM devices
             WHERE id = ?
            """,
            (_DEFAULT_TENANT_ID, str(device_id or '').strip()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_fhrp_member_scope(member_id: str) -> dict[str, str | None] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT group_row.id AS group_id, group_row.security_tenant_id,
                   group_row.address_space_id, device.id AS device_id,
                   COALESCE(NULLIF(btrim(device.tenant_id), ''), ?) AS device_tenant_id,
                   device.site_id
              FROM ipam_fhrp_group_members member
              JOIN ipam_fhrp_groups group_row ON group_row.id = member.group_id
              JOIN devices device ON device.id = member.device_id
             WHERE member.id = ?
            """,
            (_DEFAULT_TENANT_ID, str(member_id or '').strip()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_fhrp_vip_scope(vip_id: str) -> dict[str, str | None] | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT vip.address_space_id,
                   COALESCE(NULLIF(btrim(vip.tenant_id), ''), ?) AS tenant_id,
                   prefix.site_id
              FROM ipam_vips vip
              LEFT JOIN prefixes prefix ON prefix.id = vip.prefix_id
             WHERE vip.id = ?
            """,
            (_DEFAULT_TENANT_ID, str(vip_id or '').strip()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _operation_group(
    conn,
    *,
    group_id: str,
    security_tenant_id: str,
    operation: str,
    idempotency_key: str | None,
    payload: dict,
) -> tuple[dict[str, Any] | None, dict | None]:
    return _begin_group_write(
        conn,
        group_id=group_id,
        security_tenant_id=security_tenant_id,
        operation=operation,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def create_fhrp_group(
    *,
    address_space_id: str,
    security_tenant_id: str,
    group_type: str,
    protocol: str,
    group_id: str,
    address_family: int,
    display_name: str = '',
    status: str = 'active',
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any]:
    normalized_tenant = _tenant(security_tenant_id)
    normalized_space = str(address_space_id or '').strip()
    normalized_type = str(group_type or '').strip().lower()
    normalized_protocol = str(protocol or '').strip().lower()
    normalized_local_id = str(group_id or '').strip()
    normalized_family = int(address_family)
    normalized_name = str(display_name or '').strip()
    normalized_status = str(status or 'active').strip().lower()
    _validate_group_protocol(normalized_type, normalized_protocol)
    if not normalized_space or not normalized_local_id:
        raise ValueError('Explicit address space and local group id are required')
    if normalized_family not in {4, 6}:
        raise ValueError('FHRP address family must be 4 or 6')
    if normalized_status not in {'active', 'disabled'}:
        raise ValueError('FHRP group status must be active or disabled')

    payload = {
        'address_space_id': normalized_space,
        'group_type': normalized_type,
        'protocol': normalized_protocol,
        'group_id': normalized_local_id,
        'address_family': normalized_family,
        'display_name': normalized_name,
        'status': normalized_status,
    }
    operation = 'ipam.fhrp_group.create'
    conn = get_db_connection()
    try:
        lock_ipam_scope(
            conn,
            security_tenant_id=normalized_tenant,
            address_space_id=normalized_space,
        )
        replay = _replay_or_store_result(
            conn,
            tenant_id=normalized_tenant,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        space = _assert_active_space(conn, normalized_space, normalized_tenant)
        now = _now()
        resource_id = f'fhrp-{uuid.uuid4().hex}'
        conn.execute(
            """
            INSERT INTO ipam_fhrp_groups
                (id, security_tenant_id, address_space_id, group_type, protocol,
                 group_id, address_family, display_name, status, revision,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                resource_id, normalized_tenant, normalized_space,
                normalized_type, normalized_protocol, normalized_local_id,
                normalized_family, normalized_name, normalized_status, now, now,
            ),
        )
        result = _load_group_detail(conn, resource_id) or {}
        _store_idempotency_response(
            conn,
            tenant_id=normalized_tenant,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=result,
            resource_type='ipam_fhrp_group',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='info',
            summary=f'Created {normalized_protocol.upper()} group {normalized_local_id}',
            target_type='ipam_fhrp_group',
            target_id=resource_id,
            target_name=normalized_name or normalized_local_id,
            after=result,
            details={
                'address_space_id': normalized_space,
                'address_space_name': space['name'],
                'group_type': normalized_type,
                'protocol': normalized_protocol,
                'address_family': normalized_family,
            },
        )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('FHRP group identity already exists') from exc
        raise
    finally:
        conn.close()


def update_fhrp_group(
    group_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
    **fields,
) -> dict[str, Any] | None:
    normalized_id = str(group_id or '').strip()
    normalized_fields = dict(fields)
    for key in ('group_type', 'protocol', 'group_id', 'status'):
        if key in normalized_fields and normalized_fields[key] is not None:
            normalized_fields[key] = str(normalized_fields[key]).strip().lower() if key in {'group_type', 'protocol', 'status'} else str(normalized_fields[key]).strip()
    if 'display_name' in normalized_fields:
        normalized_fields['display_name'] = str(normalized_fields['display_name'] or '').strip()
    payload = {'expected_revision': int(expected_revision), **normalized_fields}
    operation = 'ipam.fhrp_group.update'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        old = dict(group)
        current_revision = _check_expected_revision(group, expected_revision)
        target_type = normalized_fields.get('group_type', group['group_type'])
        target_protocol = normalized_fields.get('protocol', group['protocol'])
        target_family = normalized_fields.get('address_family', group['address_family'])
        _validate_group_protocol(str(target_type), str(target_protocol))
        if int(target_family) not in {4, 6}:
            raise ValueError('FHRP address family must be 4 or 6')
        target_status = normalized_fields.get('status', group['status'])
        if target_status not in {'active', 'disabled'}:
            raise ValueError('FHRP group status must be active or disabled')
        if target_protocol != group['protocol'] or int(target_family) != int(group['address_family']):
            _assert_protocol_family_compatible(
                conn,
                group_id=normalized_id,
                protocol=str(target_protocol),
                address_family=int(target_family),
            )

        updates: list[str] = []
        params: list[Any] = []
        for field_name in ('group_type', 'protocol', 'group_id', 'address_family', 'display_name', 'status'):
            if field_name in normalized_fields:
                value = normalized_fields[field_name]
                if field_name == 'address_family':
                    value = int(value)
                updates.append(f'{field_name} = ?')
                params.append(value)
        if updates:
            now = _now()
            updates.extend(('revision = revision + 1', 'updated_at = ?'))
            params.extend((now, normalized_id, current_revision))
            changed = conn.execute(
                f"UPDATE ipam_fhrp_groups SET {', '.join(updates)} WHERE id = ? AND revision = ?",
                tuple(params),
            )
            if int(getattr(changed, 'rowcount', 0) or 0) != 1:
                raise ValueError('FHRP group revision is stale; refresh and retry')
        result = _load_group_detail(conn, normalized_id) or {}
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=result,
            resource_type='ipam_fhrp_group',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='info',
            summary=f'Updated {group["protocol"].upper()} group {group["group_id"]}',
            target_type='ipam_fhrp_group',
            target_id=normalized_id,
            target_name=str(result.get('display_name') or result.get('group_id') or ''),
            before=old,
            after=result,
            details={'address_space_id': group['address_space_id']},
        )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('FHRP group identity already exists') from exc
        raise
    finally:
        conn.close()


def delete_fhrp_group(
    group_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    normalized_id = str(group_id or '').strip()
    payload = {'id': normalized_id, 'expected_revision': int(expected_revision)}
    operation = 'ipam.fhrp_group.delete'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        current_revision = _check_expected_revision(group, expected_revision)
        before = _load_group_detail(conn, normalized_id) or dict(group)
        member_count = conn.execute(
            'SELECT COUNT(*) AS count FROM ipam_fhrp_group_members WHERE group_id = ?',
            (normalized_id,),
        ).fetchone()
        vip_count = conn.execute(
            'SELECT COUNT(*) AS count FROM ipam_fhrp_group_vips WHERE group_id = ?',
            (normalized_id,),
        ).fetchone()
        if int(member_count['count'] or 0) or int(vip_count['count'] or 0):
            raise ValueError('Cannot delete an FHRP group while members or VIP links remain')
        conn.execute(
            'DELETE FROM ipam_fhrp_groups WHERE id = ? AND revision = ?',
            (normalized_id, current_revision),
        )
        response = {'ok': True, 'id': normalized_id, 'revision': current_revision}
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
            resource_type='ipam_fhrp_group',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='warning',
            summary=f'Deleted {group["protocol"].upper()} group {group["group_id"]}',
            target_type='ipam_fhrp_group',
            target_id=normalized_id,
            target_name=str(group.get('display_name') or group['group_id']),
            before=before,
            details={'address_space_id': group['address_space_id']},
        )
        conn.commit()
        return response
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23503':
            raise ValueError('Cannot delete an FHRP group while it is referenced') from exc
        raise
    finally:
        conn.close()


def _resolve_member_interface(
    conn,
    *,
    device_id: str,
    interface_name: str,
    interface_id: str | None,
) -> tuple[dict, str]:
    normalized_name = normalize_interface_name(interface_name)
    if not normalized_name:
        raise ValueError('FHRP member interface name is required')
    rows = conn.execute(
        "SELECT id, device_id, interface_name FROM interfaces WHERE device_id = ? ORDER BY id FOR SHARE",
        (device_id,),
    ).fetchall()
    matches = [
        dict(row)
        for row in rows
        if normalize_interface_name(str(row['interface_name'] or '')) == normalized_name
    ]
    if interface_id:
        selected = next((row for row in matches if str(row['id']) == interface_id), None)
        if selected is None:
            raise ValueError('Interface does not exist on the specified device or does not match its name')
        return selected, normalize_interface_name(str(selected['interface_name']))
    if not matches:
        raise ValueError('FHRP member interface does not exist on the specified device')
    if len(matches) > 1:
        raise ValueError('FHRP member interface name is ambiguous on the specified device')
    selected = matches[0]
    return selected, normalize_interface_name(str(selected['interface_name']))


def add_fhrp_group_member(
    group_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    device_id: str,
    interface_name: str,
    interface_id: str | None = None,
    role: str | None = None,
    priority: int | None = None,
    status: str = 'active',
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    normalized_group_id = str(group_id or '').strip()
    normalized_device_id = str(device_id or '').strip()
    normalized_interface = str(interface_name or '').strip()
    normalized_interface_id = str(interface_id or '').strip() or None
    normalized_role = str(role or '').strip() or None
    normalized_status = str(status or 'active').strip().lower()
    if not normalized_device_id or not normalized_interface:
        raise ValueError('FHRP member device and interface are required')
    if normalized_status not in {'active', 'disabled'}:
        raise ValueError('FHRP member status must be active or disabled')
    if priority is not None and not 0 <= int(priority) <= 255:
        raise ValueError('FHRP member priority must be between 0 and 255')
    requested_normalized_name = normalize_interface_name(normalized_interface)
    payload = {
        'expected_revision': int(expected_revision),
        'device_id': normalized_device_id,
        'interface_name': requested_normalized_name,
        'interface_id': normalized_interface_id,
        'role': normalized_role,
        'priority': int(priority) if priority is not None else None,
        'status': normalized_status,
    }
    operation = 'ipam.fhrp_group.member.add'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_group_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        current_revision = _check_expected_revision(group, expected_revision)
        device = conn.execute(
            """
            SELECT id, COALESCE(NULLIF(btrim(tenant_id), ''), ?) AS tenant_id
              FROM devices
             WHERE id = ?
             FOR SHARE
            """,
            (_DEFAULT_TENANT_ID, normalized_device_id),
        ).fetchone()
        if not device:
            raise ValueError('FHRP member device not found')
        if _tenant(device['tenant_id']) != _tenant(group['security_tenant_id']):
            raise ValueError('FHRP member device does not belong to the group security tenant')
        interface, canonical_name = _resolve_member_interface(
            conn,
            device_id=normalized_device_id,
            interface_name=normalized_interface,
            interface_id=normalized_interface_id,
        )
        now = _now()
        new_member_id = f'fhrpm-{uuid.uuid4().hex}'
        _advance_group_revision(conn, normalized_group_id, current_revision, now)
        conn.execute(
            """
            INSERT INTO ipam_fhrp_group_members
                (id, group_id, device_id, interface_id, interface_name,
                 normalized_interface_name, role, priority, status, revision,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                new_member_id, normalized_group_id, normalized_device_id,
                normalized_interface_id, interface['interface_name'], canonical_name,
                normalized_role, int(priority) if priority is not None else None,
                normalized_status, now, now,
            ),
        )
        result_row = conn.execute(
            """
            SELECT member.id, member.group_id, member.device_id,
                   device.hostname AS device_name, member.interface_id,
                   member.interface_name, member.normalized_interface_name,
                   member.role, member.priority, member.status, member.revision,
                   member.created_at, member.updated_at
              FROM ipam_fhrp_group_members member
              JOIN devices device ON device.id = member.device_id
             WHERE member.id = ?
            """,
            (new_member_id,),
        ).fetchone()
        result = dict(result_row) if result_row else {'id': new_member_id}
        _stringify_timestamps(result, 'created_at', 'updated_at')
        result['group_revision'] = current_revision + 1
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=result,
            resource_type='ipam_fhrp_group_member',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='info',
            summary=f'Added {canonical_name} on {device["id"]} to {group["protocol"].upper()} group',
            target_type='ipam_fhrp_group_member',
            target_id=new_member_id,
            target_name=canonical_name,
            after=result,
            details={'group_id': normalized_group_id, 'device_id': normalized_device_id},
        )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('FHRP member interface is already registered in this group') from exc
        raise
    finally:
        conn.close()


def remove_fhrp_group_member(
    group_id: str,
    member_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    normalized_group_id = str(group_id or '').strip()
    normalized_member_id = str(member_id or '').strip()
    payload = {'id': normalized_member_id, 'expected_revision': int(expected_revision)}
    operation = 'ipam.fhrp_group.member.remove'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_group_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        current_revision = _check_expected_revision(group, expected_revision)
        member = conn.execute(
            """
            SELECT id, device_id, interface_name, normalized_interface_name
              FROM ipam_fhrp_group_members
             WHERE id = ? AND group_id = ?
             FOR UPDATE
            """,
            (normalized_member_id, normalized_group_id),
        ).fetchone()
        if not member:
            conn.rollback()
            return None
        now = _now()
        _advance_group_revision(conn, normalized_group_id, current_revision, now)
        conn.execute(
            'DELETE FROM ipam_fhrp_group_members WHERE id = ? AND group_id = ?',
            (normalized_member_id, normalized_group_id),
        )
        response = {
            'ok': True,
            'id': normalized_member_id,
            'group_revision': current_revision + 1,
        }
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
            resource_type='ipam_fhrp_group_member',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='warning',
            summary=f'Removed {member["normalized_interface_name"]} from {group["protocol"].upper()} group',
            target_type='ipam_fhrp_group_member',
            target_id=normalized_member_id,
            target_name=member['interface_name'],
            before=dict(member),
            details={
                'group_id': normalized_group_id,
                'device_id': member['device_id'],
            },
        )
        conn.commit()
        return response
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_vip_for_group(conn, group: dict, vip_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT vip.id, vip.address, vip.address_inet,
               family(vip.address_inet) AS address_family,
               vip.prefix_id, vip.address_space_id, vip.vip_type,
               vip.tenant_id, vip.status, vip.revision,
               prefix.address_space_id AS prefix_address_space_id,
               COALESCE(NULLIF(btrim(prefix.tenant_id), ''), ?) AS prefix_tenant_id,
               COALESCE(NULLIF(btrim(vip.tenant_id), ''), ?) AS normalized_tenant_id
          FROM ipam_vips vip
          JOIN prefixes prefix ON prefix.id = vip.prefix_id
         WHERE vip.id = ?
         FOR UPDATE OF vip
        """,
        (_DEFAULT_TENANT_ID, _DEFAULT_TENANT_ID, vip_id),
    ).fetchone()
    if not row:
        raise ValueError('VIP not found')
    vip = dict(row)
    if not vip['address_space_id'] or not vip['prefix_id'] or vip['address_inet'] is None:
        raise ValueError('FHRP groups can only link explicitly scoped IPAM VIPs')
    if str(vip['address_space_id']) != str(group['address_space_id']):
        raise ValueError('VIP and FHRP group must use the same address space')
    if str(vip['prefix_address_space_id']) != str(group['address_space_id']):
        raise ValueError('VIP Prefix and FHRP group must use the same address space')
    if _tenant(vip['normalized_tenant_id']) != _tenant(group['security_tenant_id']):
        raise ValueError('VIP and FHRP group must use the same security tenant')
    if _tenant(vip['prefix_tenant_id']) != _tenant(group['security_tenant_id']):
        raise ValueError('VIP Prefix and FHRP group must use the same security tenant')
    if str(vip['vip_type'] or '').strip().lower() != str(group['protocol']).lower():
        raise ValueError('VIP protocol must match the FHRP group protocol')
    if int(vip['address_family'] or 0) != int(group['address_family']):
        raise ValueError('VIP address family must match the FHRP group address family')
    if str(vip.get('status') or 'active').strip().lower() in {'released', 'deprecated', 'disabled'}:
        raise ValueError('Inactive VIPs cannot be linked to an FHRP or Anycast group')
    return vip


def attach_fhrp_group_vip(
    group_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    vip_id: str,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    normalized_group_id = str(group_id or '').strip()
    normalized_vip_id = str(vip_id or '').strip()
    payload = {'expected_revision': int(expected_revision), 'vip_id': normalized_vip_id}
    operation = 'ipam.fhrp_group.vip.attach'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_group_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        current_revision = _check_expected_revision(group, expected_revision)
        vip = _load_vip_for_group(conn, group, normalized_vip_id)
        if group['group_type'] == 'anycast':
            existing_anycast_vip = conn.execute(
                'SELECT 1 FROM ipam_fhrp_group_vips WHERE group_id = ? LIMIT 1 FOR UPDATE',
                (normalized_group_id,),
            ).fetchone()
            if existing_anycast_vip:
                raise ValueError('Anycast groups use one formal IPAM VIP')
        link = conn.execute(
            'SELECT group_id FROM ipam_fhrp_group_vips WHERE vip_id = ? FOR UPDATE',
            (normalized_vip_id,),
        ).fetchone()
        if link:
            raise ValueError('VIP is already linked to an FHRP or Anycast group')
        now = _now()
        _advance_group_revision(conn, normalized_group_id, current_revision, now)
        relation_id = f'fhrpv-{uuid.uuid4().hex}'
        conn.execute(
            """
            INSERT INTO ipam_fhrp_group_vips (id, group_id, vip_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (relation_id, normalized_group_id, normalized_vip_id, now),
        )
        result = {
            'id': relation_id,
            'group_id': normalized_group_id,
            'vip_id': normalized_vip_id,
            'address': str(vip['address']),
            'vip_type': str(vip['vip_type']),
            'group_revision': current_revision + 1,
        }
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=result,
            resource_type='ipam_fhrp_group_vip',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='info',
            summary=f'Linked VIP {vip["address"]} to {group["protocol"].upper()} group',
            target_type='ipam_fhrp_group_vip',
            target_id=relation_id,
            target_name=str(vip['address']),
            after=result,
            details={
                'group_id': normalized_group_id,
                'vip_id': normalized_vip_id,
                'address_space_id': group['address_space_id'],
            },
        )
        conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'sqlstate', '') == '23505':
            raise ValueError('VIP is already linked to an FHRP or Anycast group') from exc
        raise
    finally:
        conn.close()


def detach_fhrp_group_vip(
    group_id: str,
    vip_id: str,
    *,
    security_tenant_id: str,
    expected_revision: int,
    idempotency_key: str | None = None,
    audit_context: dict | None = None,
) -> dict[str, Any] | None:
    normalized_group_id = str(group_id or '').strip()
    normalized_vip_id = str(vip_id or '').strip()
    payload = {'expected_revision': int(expected_revision), 'vip_id': normalized_vip_id}
    operation = 'ipam.fhrp_group.vip.detach'
    conn = get_db_connection()
    try:
        group, replay = _operation_group(
            conn,
            group_id=normalized_group_id,
            security_tenant_id=security_tenant_id,
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if replay is not None:
            return replay
        if not group:
            conn.rollback()
            return None
        current_revision = _check_expected_revision(group, expected_revision)
        relation = conn.execute(
            """
            SELECT relation.id, relation.group_id, relation.vip_id,
                   vip.address, vip.vip_type
              FROM ipam_fhrp_group_vips relation
              JOIN ipam_vips vip ON vip.id = relation.vip_id
             WHERE relation.group_id = ? AND relation.vip_id = ?
             FOR UPDATE OF relation
            """,
            (normalized_group_id, normalized_vip_id),
        ).fetchone()
        if not relation:
            conn.rollback()
            return None
        now = _now()
        _advance_group_revision(conn, normalized_group_id, current_revision, now)
        conn.execute(
            'DELETE FROM ipam_fhrp_group_vips WHERE id = ?', (relation['id'],)
        )
        response = {
            'ok': True,
            'group_id': normalized_group_id,
            'vip_id': normalized_vip_id,
            'group_revision': current_revision + 1,
        }
        _store_idempotency_response(
            conn,
            tenant_id=_tenant(group['security_tenant_id']),
            operation=operation,
            idempotency_key=idempotency_key,
            payload=payload,
            response=response,
            resource_type='ipam_fhrp_group_vip',
        )
        _write_ipam_audit(
            conn,
            audit_context,
            event_type=operation,
            severity='warning',
            summary=f'Unlinked VIP {relation["address"]} from {group["protocol"].upper()} group',
            target_type='ipam_fhrp_group_vip',
            target_id=str(relation['id']),
            target_name=str(relation['address']),
            before=dict(relation),
            details={'group_id': normalized_group_id, 'vip_id': normalized_vip_id},
        )
        conn.commit()
        return response
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
