"""Stack member physical asset ledger, idempotent import, SNMP reconciliation, and replacement."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.audit_service import log_audit_event


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(value: Any) -> str:
    return str(value or '').strip()


def _clean_int(value: Any) -> int | None:
    if value is None or str(value).strip() == '':
        return None
    return int(str(value).strip())


def list_stack_members(asset_id: str, *, include_history: bool = False) -> list[dict[str, Any]]:
    """Return physical chassis member records for a logical stack asset."""
    normalized_id = _clean(asset_id)
    if not normalized_id:
        return []
    conn = get_db_connection()
    try:
        status_clause = '' if include_history else " AND m.status = 'active'"
        rows = conn.execute(
            f"""SELECT m.*, r.name AS resolved_rack_name
                  FROM asset_stack_members m
                  LEFT JOIN racks r ON r.id = m.rack_id
                 WHERE m.asset_id = ?{status_clause}
                 ORDER BY CASE WHEN m.status = 'active' THEN 0 ELSE 1 END,
                          m.member_number ASC, m.created_at DESC""",
            (normalized_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if not item.get('rack_name') and item.get('resolved_rack_name'):
                item['rack_name'] = item['resolved_rack_name']
            item.pop('resolved_rack_name', None)
            items.append(item)
        return items
    finally:
        conn.close()


def _evaluate_stack_member_import(
    conn,
    rows: list[dict[str, Any]],
    *,
    tenant_id: str = 'tenant-default',
) -> dict[str, Any]:
    effective_tenant = _clean(tenant_id) or 'tenant-default'
    stack_rows = conn.execute(
        """SELECT pa.id, pa.asset_tag, pa.hostname, pa.management_ip,
                  COALESCE(NULLIF(d.tenant_id, ''), NULLIF(s.tenant_id, ''), 'tenant-default') AS tenant_id
             FROM physical_assets pa
             LEFT JOIN devices d ON d.asset_id = pa.id
             LEFT JOIN sites s ON s.id = pa.site_id
            WHERE pa.asset_type = 'network_device'
              AND COALESCE(NULLIF(d.tenant_id, ''), NULLIF(s.tenant_id, ''), 'tenant-default') = ?""",
        (effective_tenant,),
    ).fetchall()
    stacks_by_tag = {
        _clean(r['asset_tag']).lower(): dict(r)
        for r in stack_rows
        if _clean(r['asset_tag'])
    }
    stacks_by_hostname = {
        _clean(r['hostname']).lower(): dict(r)
        for r in stack_rows
        if _clean(r['hostname'])
    }

    rack_rows = conn.execute('SELECT id, name FROM racks').fetchall()
    racks_by_id = {_clean(r['id']): dict(r) for r in rack_rows if _clean(r['id'])}
    racks_by_name = {_clean(r['name']).lower(): dict(r) for r in rack_rows if _clean(r['name'])}

    existing_active = [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM asset_stack_members
                WHERE status = 'active' AND COALESCE(tenant_id, 'tenant-default') = ?""",
            (effective_tenant,),
        ).fetchall()
    ]
    active_by_slot = {
        (str(m['asset_id']), int(m['member_number'])): m
        for m in existing_active
    }
    active_by_sn = {
        _clean(m['serial_number']).lower(): m
        for m in existing_active
        if _clean(m['serial_number'])
    }
    active_by_tag = {
        _clean(m['physical_asset_tag']).lower(): m
        for m in existing_active
        if _clean(m['physical_asset_tag'])
    }

    batch_slots: dict[tuple[str, int], int] = {}
    batch_sns: dict[str, int] = {}
    batch_tags: dict[str, int] = {}
    batch_rack_units: list[tuple[str, int, int, int]] = []

    items: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    counts = {'create': 0, 'update': 0, 'existing': 0, 'conflict': 0}

    for idx, raw in enumerate(rows, start=1):
        row_num = int(raw.get('row_number') or idx)
        stack_tag = _clean(raw.get('stack_asset_tag') or raw.get('asset_tag'))
        phys_tag = _clean(raw.get('physical_asset_tag'))
        sn = _clean(raw.get('serial_number') or raw.get('sn'))
        model = _clean(raw.get('model'))
        rack_id_input = _clean(raw.get('rack_id'))
        rack_name_input = _clean(raw.get('rack_name'))
        notes = _clean(raw.get('notes'))
        row_conflicts: list[dict[str, Any]] = []

        def _add_conflict(field: str, message: str) -> None:
            entry = {'row_number': row_num, 'field': field, 'message': message}
            row_conflicts.append(entry)
            conflicts.append(entry)

        try:
            member_num = _clean_int(raw.get('member_number'))
        except ValueError:
            member_num = None
        if member_num is None or member_num < 1:
            _add_conflict('member_number', 'Member number must be an integer >= 1')

        try:
            u_start = _clean_int(raw.get('u_start'))
        except ValueError:
            u_start = -1
        if u_start is not None and u_start < 1:
            _add_conflict('u_start', 'Rack U start must be an integer >= 1')

        try:
            u_height = _clean_int(raw.get('u_height'))
        except ValueError:
            u_height = -1
        if u_height is None:
            u_height = 1
        elif u_height < 1:
            _add_conflict('u_height', 'Rack U height must be an integer >= 1')

        stack = stacks_by_tag.get(stack_tag.lower()) or stacks_by_hostname.get(stack_tag.lower())
        if not stack:
            _add_conflict('stack_asset_tag', f'Logical stack asset not found: {stack_tag or "(empty)"}')

        resolved_rack_id: str | None = None
        resolved_rack_name = rack_name_input
        if rack_id_input:
            if rack_id_input in racks_by_id:
                resolved_rack_id = rack_id_input
                resolved_rack_name = resolved_rack_name or racks_by_id[rack_id_input]['name']
            else:
                _add_conflict('rack_id', f'Rack not found: {rack_id_input}')
        elif rack_name_input:
            matched_rack = racks_by_name.get(rack_name_input.lower())
            if matched_rack:
                resolved_rack_id = matched_rack['id']
                resolved_rack_name = matched_rack['name']

        existing_slot = None
        if stack and member_num is not None and member_num >= 1:
            slot_key = (str(stack['id']), member_num)
            if slot_key in batch_slots:
                _add_conflict(
                    'member_number',
                    f'Duplicate stack member slot ({stack_tag} #{member_num}) also appears on row {batch_slots[slot_key]}',
                )
            else:
                batch_slots[slot_key] = row_num
            existing_slot = active_by_slot.get(slot_key)

        if sn:
            sn_key = sn.lower()
            if sn_key in batch_sns:
                _add_conflict('serial_number', f'Duplicate serial number {sn} in import file (row {batch_sns[sn_key]})')
            else:
                batch_sns[sn_key] = row_num
            owner = active_by_sn.get(sn_key)
            if owner and (not existing_slot or str(owner['id']) != str(existing_slot['id'])):
                _add_conflict(
                    'serial_number',
                    f'Serial number {sn} is already assigned to another active stack member ({owner["asset_id"]} #{owner["member_number"]})',
                )

        if phys_tag:
            tag_key = phys_tag.lower()
            if tag_key in batch_tags:
                _add_conflict('physical_asset_tag', f'Duplicate physical asset tag {phys_tag} in import file (row {batch_tags[tag_key]})')
            else:
                batch_tags[tag_key] = row_num
            owner = active_by_tag.get(tag_key)
            if owner and (not existing_slot or str(owner['id']) != str(existing_slot['id'])):
                _add_conflict(
                    'physical_asset_tag',
                    f'Physical asset tag {phys_tag} is already assigned to another active stack member ({owner["asset_id"]} #{owner["member_number"]})',
                )

        rack_key = resolved_rack_id or resolved_rack_name.lower()
        if rack_key and u_start is not None and u_start >= 1 and u_height >= 1:
            u_end = u_start + u_height - 1
            for prev_rack, prev_start, prev_end, prev_row in batch_rack_units:
                if prev_rack == rack_key and not (u_end < prev_start or u_start > prev_end):
                    _add_conflict(
                        'u_start',
                        f'Rack U range U{u_start}-U{u_end} overlaps with row {prev_row} (U{prev_start}-U{prev_end})',
                    )
                    break
            batch_rack_units.append((rack_key, u_start, u_end, row_num))

        if row_conflicts:
            action = 'conflict'
        elif existing_slot:
            same = (
                _clean(existing_slot.get('physical_asset_tag')) == phys_tag
                and _clean(existing_slot.get('serial_number')).lower() == sn.lower()
                and _clean(existing_slot.get('model')) == model
                and _clean(existing_slot.get('rack_id')) == _clean(resolved_rack_id)
                and _clean(existing_slot.get('rack_name')) == resolved_rack_name
                and existing_slot.get('u_start') == u_start
                and int(existing_slot.get('u_height') or 1) == u_height
                and _clean(existing_slot.get('notes')) == notes
            )
            action = 'existing' if same else 'update'
        else:
            action = 'create'

        counts[action] += 1
        items.append({
            'row_number': row_num,
            'action': action,
            'asset_id': str(stack['id']) if stack else None,
            'stack_asset_tag': stack_tag,
            'member_number': member_num,
            'existing_member_id': str(existing_slot['id']) if existing_slot else None,
            'physical_asset_tag': phys_tag,
            'serial_number': sn,
            'model': model,
            'rack_id': resolved_rack_id,
            'rack_name': resolved_rack_name,
            'u_start': u_start,
            'u_height': u_height,
            'notes': notes,
            'conflicts': row_conflicts,
        })

    return {
        'summary': {
            'total': len(rows),
            'create': counts['create'],
            'update': counts['update'],
            'existing': counts['existing'],
            'conflict': counts['conflict'],
        },
        'items': items,
        'conflicts': conflicts,
        'can_commit': len(conflicts) == 0,
    }


def preview_stack_member_import(
    rows: list[dict[str, Any]],
    *,
    tenant_id: str = 'tenant-default',
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        return _evaluate_stack_member_import(conn, rows, tenant_id=tenant_id)
    finally:
        conn.close()


def commit_stack_member_import(
    rows: list[dict[str, Any]],
    *,
    tenant_id: str = 'tenant-default',
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_tenant = _clean(tenant_id) or 'tenant-default'
    conn = get_db_connection()
    try:
        preview = _evaluate_stack_member_import(conn, rows, tenant_id=effective_tenant)
        if not preview['can_commit']:
            first = preview['conflicts'][0]
            raise ValueError(
                f"Stack member import has {len(preview['conflicts'])} conflict(s); "
                f"row {first['row_number']} ({first['field']}): {first['message']}"
            )
        now = _utc_now()
        created_ids: list[str] = []
        updated_ids: list[str] = []
        skipped_ids: list[str] = []
        for item in preview['items']:
            if item['action'] == 'existing':
                skipped_ids.append(str(item['existing_member_id']))
                continue
            if item['action'] == 'create':
                member_id = f"stack-member-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """INSERT INTO asset_stack_members (
                           id, asset_id, member_number, physical_asset_tag, serial_number,
                           model, rack_id, rack_name, u_start, u_height, status,
                           notes, tenant_id, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                    (
                        member_id, item['asset_id'], item['member_number'],
                        item['physical_asset_tag'], item['serial_number'],
                        item['model'], item['rack_id'], item['rack_name'],
                        item['u_start'], item['u_height'], item['notes'],
                        effective_tenant, now, now,
                    ),
                )
                created_ids.append(member_id)
            elif item['action'] == 'update':
                member_id = str(item['existing_member_id'])
                conn.execute(
                    """UPDATE asset_stack_members
                          SET physical_asset_tag = ?, serial_number = ?, model = ?,
                              rack_id = ?, rack_name = ?, u_start = ?, u_height = ?,
                              notes = ?, updated_at = ?
                        WHERE id = ?""",
                    (
                        item['physical_asset_tag'], item['serial_number'], item['model'],
                        item['rack_id'], item['rack_name'], item['u_start'], item['u_height'],
                        item['notes'], now, member_id,
                    ),
                )
                updated_ids.append(member_id)

        if audit_context:
            log_audit_event(
                event_type='asset.stack_members.import',
                category='cmdb',
                severity='info',
                status='success',
                summary=(
                    f'Imported stack members: created={len(created_ids)}, '
                    f'updated={len(updated_ids)}, unchanged={len(skipped_ids)}'
                ),
                actor_username=audit_context.get('actor_username'),
                actor_role=audit_context.get('actor_role'),
                target_type='asset_stack_members',
                conn=conn,
            )
        conn.commit()
        return {
            'ok': True,
            'created': len(created_ids),
            'updated': len(updated_ids),
            'unchanged': len(skipped_ids),
            'created_ids': created_ids,
            'updated_ids': updated_ids,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reconcile_stack_members_with_snmp(asset_id: str) -> dict[str, Any]:
    """Reconcile active stack member records against SNMP ``asset_chassis_members`` observations.

    Matches primarily by confirmed serial number and never overwrites operator-
    maintained physical asset tags, rack coordinates, or replacement history.
    """
    normalized_id = _clean(asset_id)
    conn = get_db_connection()
    try:
        members = [
            dict(r)
            for r in conn.execute(
                """SELECT * FROM asset_stack_members
                    WHERE asset_id = ? AND status = 'active'
                    ORDER BY member_number""",
                (normalized_id,),
            ).fetchall()
        ]
        observed = [
            dict(r)
            for r in conn.execute(
                """SELECT * FROM asset_chassis_members
                    WHERE asset_id = ?
                    ORDER BY entity_index""",
                (normalized_id,),
            ).fetchall()
        ]
        now = _utc_now()
        obs_by_sn = {
            _clean(o['serial_number']).lower(): o
            for o in observed
            if _clean(o['serial_number'])
        }
        obs_by_index = {int(o['entity_index']): o for o in observed}
        matched_obs_indices: set[int] = set()
        matched_members: list[dict[str, Any]] = []
        missing_members: list[dict[str, Any]] = []
        mismatched_members: list[dict[str, Any]] = []

        # Pass 1: match primarily by confirmed serial number (independent of SNMP entity_index)
        unmatched_members: list[dict[str, Any]] = []
        for member in members:
            member_sn = _clean(member['serial_number']).lower()
            matched_obs = obs_by_sn.get(member_sn) if member_sn else None
            if matched_obs:
                entity_idx = int(matched_obs['entity_index'])
                matched_obs_indices.add(entity_idx)
                conn.execute(
                    """UPDATE asset_stack_members
                          SET entity_index = ?, last_reconciled_at = ?,
                              reconciliation_status = 'matched', updated_at = ?
                        WHERE id = ?""",
                    (entity_idx, now, now, member['id']),
                )
                matched_members.append({
                    'member_id': member['id'],
                    'member_number': member['member_number'],
                    'physical_asset_tag': member['physical_asset_tag'],
                    'serial_number': member['serial_number'],
                    'entity_index': entity_idx,
                })
            else:
                unmatched_members.append(member)

        # Pass 2: check remaining unmatched members only against still-unmatched entity indices
        for member in unmatched_members:
            member_sn = _clean(member['serial_number']).lower()
            slot_obs = obs_by_index.get(int(member['member_number']))
            if (
                slot_obs
                and int(slot_obs['entity_index']) not in matched_obs_indices
                and _clean(slot_obs['serial_number'])
                and member_sn
            ):
                entity_idx = int(slot_obs['entity_index'])
                matched_obs_indices.add(entity_idx)
                conn.execute(
                    """UPDATE asset_stack_members
                          SET entity_index = ?, last_reconciled_at = ?,
                              reconciliation_status = 'sn_mismatch', updated_at = ?
                        WHERE id = ?""",
                    (entity_idx, now, now, member['id']),
                )
                mismatched_members.append({
                    'member_id': member['id'],
                    'member_number': member['member_number'],
                    'registered_sn': member['serial_number'],
                    'observed_sn': slot_obs['serial_number'],
                    'entity_index': entity_idx,
                })
            else:
                conn.execute(
                    """UPDATE asset_stack_members
                          SET last_reconciled_at = ?,
                              reconciliation_status = 'missing_in_snmp', updated_at = ?
                        WHERE id = ?""",
                    (now, now, member['id']),
                )
                missing_members.append({
                    'member_id': member['id'],
                    'member_number': member['member_number'],
                    'physical_asset_tag': member['physical_asset_tag'],
                    'serial_number': member['serial_number'],
                })

        unregistered_chassis = [
            {
                'entity_index': int(o['entity_index']),
                'serial_number': _clean(o['serial_number']),
                'model': _clean(o['model']),
                'entity_name': _clean(o['entity_name']),
                'collected_at': str(o['collected_at']),
            }
            for o in observed
            if int(o['entity_index']) not in matched_obs_indices
        ]
        conn.commit()
        return {
            'asset_id': normalized_id,
            'reconciled_at': now,
            'matched_members': matched_members,
            'missing_members': missing_members,
            'mismatched_members': mismatched_members,
            'unregistered_chassis': unregistered_chassis,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def replace_stack_member(
    member_id: str,
    *,
    new_serial_number: str,
    new_physical_asset_tag: str = '',
    new_model: str = '',
    notes: str = '',
    audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retire an active chassis member and install its replacement at the same slot and rack position."""
    normalized_id = _clean(member_id)
    new_sn = _clean(new_serial_number)
    new_tag = _clean(new_physical_asset_tag)
    if not new_sn:
        raise ValueError('Replacement chassis requires a non-empty serial_number')

    conn = get_db_connection()
    try:
        old = conn.execute(
            "SELECT * FROM asset_stack_members WHERE id = ? FOR UPDATE",
            (normalized_id,),
        ).fetchone()
        if not old:
            raise LookupError(f'Stack member not found: {normalized_id}')
        old = dict(old)
        if str(old['status']) != 'active':
            raise ValueError('Only an active stack member can be replaced')
        if _clean(old['serial_number']).lower() == new_sn.lower():
            raise ValueError('Replacement serial_number must differ from the retiring chassis')

        tenant = _clean(old['tenant_id']) or 'tenant-default'
        dup_sn = conn.execute(
            """SELECT id FROM asset_stack_members
                WHERE status = 'active' AND COALESCE(tenant_id, 'tenant-default') = ?
                  AND lower(serial_number) = lower(?) AND id <> ?""",
            (tenant, new_sn, normalized_id),
        ).fetchone()
        if dup_sn:
            raise ValueError(f'Serial number {new_sn} is already active on another stack member')

        now = _utc_now()
        new_id = f"stack-member-{uuid.uuid4().hex[:12]}"
        # Retire old first so partial unique index on (asset_id, member_number) allows new active row
        conn.execute(
            """UPDATE asset_stack_members
                  SET status = 'replaced', retired_at = ?, updated_at = ?
                WHERE id = ?""",
            (now, now, normalized_id),
        )
        conn.execute(
            """INSERT INTO asset_stack_members (
                   id, asset_id, member_number, physical_asset_tag, serial_number,
                   model, rack_id, rack_name, u_start, u_height, status,
                   reconciliation_status, notes, tenant_id, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'unverified', ?, ?, ?, ?)""",
            (
                new_id, old['asset_id'], int(old['member_number']),
                new_tag, new_sn, _clean(new_model) or _clean(old['model']),
                old['rack_id'], _clean(old['rack_name']), old['u_start'],
                int(old['u_height'] or 1), _clean(notes), tenant, now, now,
            ),
        )
        conn.execute(
            'UPDATE asset_stack_members SET replaced_by_id = ? WHERE id = ?',
            (new_id, normalized_id),
        )
        if audit_context:
            log_audit_event(
                event_type='asset.stack_member.replace',
                category='cmdb',
                severity='warning',
                status='success',
                summary=f'Replaced stack member {old["asset_id"]} #{old["member_number"]} ({old["serial_number"]} -> {new_sn})',
                actor_username=audit_context.get('actor_username'),
                actor_role=audit_context.get('actor_role'),
                target_type='asset_stack_member',
                target_id=new_id,
                conn=conn,
            )
        conn.commit()
        new_row = conn.execute('SELECT * FROM asset_stack_members WHERE id = ?', (new_id,)).fetchone()
        old_row = conn.execute('SELECT * FROM asset_stack_members WHERE id = ?', (normalized_id,)).fetchone()
        return {
            'retired_member': dict(old_row),
            'new_member': dict(new_row),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
