"""Discovery observation and CMDB/IPAM reconciliation lifecycle."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from database import get_db_connection
from services.audit_service import log_audit_event


ACTION_TYPES = {
    'register_ip', 'update_ip_metadata', 'release_ip', 'mark_stale',
    'ignore_once', 'ignore_rule', 'create_ticket', 'update_device',
    'upsert_interface', 'register_topology',
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, default=str)


def _load(value: str | None) -> dict:
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {'value': parsed}
    except Exception:
        return {}


def create_discovery_run(*, run_type: str = 'network', requested_by: str = 'system', scope: dict | None = None, conn=None) -> str:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        run_id = f"discovery-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO discovery_runs
               (id, run_type, status, requested_by, scope_json, started_at, summary_json)
               VALUES (?, ?, 'running', ?, ?, ?, '{}')""",
            (run_id, run_type, requested_by, _json(scope), _now()),
        )
        if own_conn:
            conn.commit()
        return run_id
    finally:
        if own_conn:
            conn.close()


def record_observation(
    run_id: str, *, source_device_id: str | None, source_type: str,
    observed_type: str, observed_key: str, payload: dict,
    confidence: float = 0.5, conn=None,
) -> str:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        observation_id = f"observation-{uuid.uuid4().hex[:12]}"
        now = _now()
        conn.execute(
            """INSERT INTO discovery_observations
               (id, run_id, source_device_id, source_type, observed_type, observed_key,
                payload_json, confidence, first_seen_at, last_seen_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (observation_id, run_id, source_device_id or None, source_type,
             observed_type, observed_key, _json(payload), max(0.0, min(float(confidence), 1.0)), now, now),
        )
        if own_conn:
            conn.commit()
        return observation_id
    finally:
        if own_conn:
            conn.close()


def complete_discovery_run(run_id: str, *, status: str, summary: dict | None = None, conn=None) -> None:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        conn.execute(
            "UPDATE discovery_runs SET status = ?, completed_at = ?, summary_json = ? WHERE id = ?",
            (status, _now(), _json(summary), run_id),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def create_reconciliation_run(
    *, discovery_run_id: str | None, requested_by: str,
    findings: Iterable[dict], conn=None,
) -> dict:
    own_conn = conn is None
    conn = conn or get_db_connection()
    try:
        run_id = f"reconciliation-{uuid.uuid4().hex[:12]}"
        now = _now()
        finding_items = list(findings)
        conn.execute(
            """INSERT INTO reconciliation_runs
               (id, discovery_run_id, status, requested_by, started_at,
                total_findings, open_findings, summary_json)
               VALUES (?, ?, 'open', ?, ?, ?, ?, ?)""",
            (run_id, discovery_run_id or None, requested_by, now,
             len(finding_items), len(finding_items), _json({'finding_count': len(finding_items)})),
        )
        created = []
        for finding in finding_items:
            finding_id = f"finding-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO reconciliation_findings
                   (id, run_id, observation_id, finding_type, status, risk_level,
                    target_type, target_id, tenant_id, site_id, observed_json,
                    current_json, proposed_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (finding_id, run_id, finding.get('observation_id'), finding['finding_type'],
                 finding.get('risk_level', 'medium'), finding.get('target_type'),
                 finding.get('target_id'), finding.get('tenant_id'), finding.get('site_id'),
                 _json(finding.get('observed')), _json(finding.get('current')),
                 _json(finding.get('proposed')), now, now),
            )
            created.append(finding_id)
        if not finding_items:
            conn.execute(
                "UPDATE reconciliation_runs SET status = 'resolved', completed_at = ? WHERE id = ?",
                (now, run_id),
            )
        if own_conn:
            conn.commit()
        return {'id': run_id, 'finding_ids': created, 'total_findings': len(created)}
    finally:
        if own_conn:
            conn.close()


def materialize_current_ipam_findings(*, requested_by: str) -> dict:
    from services.ipam_service import get_ipam_reconciliation

    snapshot = get_ipam_reconciliation()
    findings: list[dict] = []
    for item in snapshot.get('undocumented_endpoints', []):
        findings.append({
            'finding_type': 'undocumented_endpoint', 'risk_level': 'medium',
            'target_type': 'ip_address', 'target_id': item.get('ip'), 'observed': item,
            'proposed': {
                'address': item.get('ip'), 'subnet_id': item.get('subnet_id'),
                'hostname': item.get('hostname'), 'mac_address': item.get('mac'),
                'interface_name': item.get('switch_port'), 'source_type': 'discovered',
            },
        })
    for item in snapshot.get('stale_ip_addresses', []):
        findings.append({
            'finding_type': 'stale_ip_address', 'risk_level': 'medium',
            'target_type': 'ip_address', 'target_id': item.get('id'),
            'current': item, 'proposed': {'status': 'deprecated'},
        })
    for item in snapshot.get('mismatched_endpoints', []):
        findings.append({
            'finding_type': 'mac_mismatch' if item.get('mac_mismatch') else 'hostname_mismatch',
            'risk_level': 'high', 'target_type': 'ip_address',
            'target_id': item.get('ipam_address_id'), 'observed': item,
            'proposed': {'hostname': item.get('endpoint_hostname'), 'mac_address': item.get('endpoint_mac')},
        })
    return create_reconciliation_run(discovery_run_id=None, requested_by=requested_by, findings=findings)


def list_runs(*, status: str = '', page: int = 1, page_size: int = 50) -> dict:
    conn = get_db_connection()
    try:
        where, params = '', []
        if status and status != 'all':
            where, params = 'WHERE status = ?', [status]
        total = conn.execute(f"SELECT COUNT(*) AS count FROM reconciliation_runs {where}", tuple(params)).fetchone()['count']
        rows = conn.execute(
            f"SELECT * FROM reconciliation_runs {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            tuple([*params, page_size, (page - 1) * page_size]),
        ).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}
    finally:
        conn.close()


def list_findings(*, run_id: str = '', status: str = '', risk_level: str = '') -> list[dict]:
    clauses, params = [], []
    for column, value in (('run_id', run_id), ('status', status), ('risk_level', risk_level)):
        if value and value != 'all':
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM reconciliation_findings {where} ORDER BY created_at DESC LIMIT 1000",
            tuple(params),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in ('observed_json', 'current_json', 'proposed_json'):
                item[field.removesuffix('_json')] = _load(item.get(field))
            result.append(item)
        return result
    finally:
        conn.close()


def request_action(finding_id: str, *, action_type: str, requested_by: str, payload: dict | None = None) -> dict:
    if action_type not in ACTION_TYPES:
        raise ValueError(f'Unsupported reconciliation action: {action_type}')
    conn = get_db_connection()
    try:
        finding = conn.execute("SELECT * FROM reconciliation_findings WHERE id = ?", (finding_id,)).fetchone()
        if not finding:
            raise ValueError('Finding not found')
        if finding['status'] not in ('open', 'accepted'):
            raise ValueError(f"Finding is already {finding['status']}")
        action_id = f"action-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO reconciliation_actions
               (id, finding_id, action_type, status, requested_by, payload_json, created_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
            (action_id, finding_id, action_type, requested_by, _json(payload), _now()),
        )
        conn.execute("UPDATE reconciliation_findings SET status = 'accepted', updated_at = ? WHERE id = ?", (_now(), finding_id))
        conn.commit()
        return {'id': action_id, 'status': 'pending'}
    finally:
        conn.close()


def _apply_action(conn, finding: dict, action: dict, approved_by: str) -> dict:
    action_type = action['action_type']
    payload = {**_load(finding.get('proposed_json')), **_load(action.get('payload_json'))}
    target_id = finding.get('target_id')
    before: dict = {}
    after: dict = {}

    if action_type == 'register_ip':
        from services.ipam_service import _create_address_with_conn
        if not payload.get('subnet_id') or not payload.get('address'):
            raise ValueError('register_ip requires subnet_id and address')
        after = _create_address_with_conn(
            conn, payload['subnet_id'], address=payload['address'],
            hostname=payload.get('hostname', ''), device_id=payload.get('device_id', ''),
            interface_id=payload.get('interface_id', ''), interface_name=payload.get('interface_name', ''),
            mac_address=payload.get('mac_address', ''), status='allocated',
            purpose=payload.get('purpose', 'reconciliation'), requested_by=approved_by,
            source_type='discovered', source_ref=finding.get('observation_id') or finding['id'],
        )
    elif action_type in ('update_ip_metadata', 'mark_stale', 'release_ip'):
        row = conn.execute("SELECT * FROM ip_addresses WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise ValueError('Target IP address not found')
        before = dict(row)
        if action_type == 'release_ip':
            now = datetime.now(timezone.utc).replace(microsecond=0)
            values = {'status': 'released', 'released_at': now.isoformat(),
                      'available_after': (now + timedelta(hours=24)).isoformat(),
                      'device_id': '', 'interface_id': '', 'interface_name': '', 'mac_address': ''}
        elif action_type == 'mark_stale':
            values = {'status': 'deprecated'}
        else:
            allowed = {'hostname', 'mac_address', 'device_id', 'interface_id', 'interface_name', 'description'}
            values = {key: value for key, value in payload.items() if key in allowed}
        if values:
            assignments = ', '.join(f"{key} = ?" for key in values)
            conn.execute(f"UPDATE ip_addresses SET {assignments}, updated_at = ? WHERE id = ?", (*values.values(), _now(), target_id))
        after_row = conn.execute("SELECT * FROM ip_addresses WHERE id = ?", (target_id,)).fetchone()
        after = dict(after_row) if after_row else {}
    elif action_type == 'update_device':
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (target_id,)).fetchone()
        if not row:
            raise ValueError('Target device not found')
        before = dict(row)
        allowed = {'hostname', 'vendor', 'platform', 'serial_number', 'model', 'os_version', 'uptime'}
        values = {key: value for key, value in payload.items() if key in allowed}
        if values:
            assignments = ', '.join(f"{key} = ?" for key in values)
            conn.execute(f"UPDATE devices SET {assignments}, source_type = 'confirmed', confirmed_by = ?, last_confirmed_at = ? WHERE id = ?", (*values.values(), approved_by, _now(), target_id))
        after = dict(conn.execute("SELECT * FROM devices WHERE id = ?", (target_id,)).fetchone())
    elif action_type == 'upsert_interface':
        device_id = payload.get('device_id')
        interface_name = payload.get('interface_name')
        if not device_id or not interface_name:
            raise ValueError('upsert_interface requires device_id and interface_name')
        existing = conn.execute("SELECT * FROM interfaces WHERE device_id = ? AND interface_name = ?", (device_id, interface_name)).fetchone()
        before = dict(existing) if existing else {}
        interface_id = existing['id'] if existing else f"interface-{uuid.uuid4().hex[:12]}"
        if not existing:
            conn.execute(
                """INSERT INTO interfaces
                   (id, device_id, interface_name, description, admin_status, oper_status,
                    mac_address, source_type, source_ref, confidence, last_confirmed_at, confirmed_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)""",
                (interface_id, device_id, interface_name, payload.get('description', ''),
                 payload.get('admin_status', 'down'), payload.get('oper_status', 'down'),
                 payload.get('mac_address', ''), finding.get('observation_id') or finding['id'],
                 float(payload.get('confidence', 0.8)), _now(), approved_by),
            )
        after = dict(conn.execute("SELECT * FROM interfaces WHERE id = ?", (interface_id,)).fetchone())
    elif action_type in ('ignore_once', 'ignore_rule', 'create_ticket', 'register_topology'):
        after = {'action': action_type, 'payload': payload}
    else:
        raise ValueError(f'Unsupported reconciliation action: {action_type}')

    log_audit_event(
        event_type=f'reconciliation.{action_type}', category='reconciliation', severity='warning',
        status='success', summary=f"Applied reconciliation action {action_type}",
        actor_username=approved_by, actor_role='Administrator', target_type=finding.get('target_type'),
        target_id=target_id, before=before, after=after,
        details={'finding_id': finding['id'], 'action_id': action['id']}, conn=conn,
    )
    return after


def approve_action(action_id: str, *, approved_by: str) -> dict:
    conn = get_db_connection()
    try:
        action_row = conn.execute("SELECT * FROM reconciliation_actions WHERE id = ?", (action_id,)).fetchone()
        if not action_row:
            raise ValueError('Action not found')
        action = dict(action_row)
        if action['status'] != 'pending':
            raise ValueError(f"Action is already {action['status']}")
        finding_row = conn.execute("SELECT * FROM reconciliation_findings WHERE id = ?", (action['finding_id'],)).fetchone()
        if not finding_row:
            raise ValueError('Finding not found')
        finding = dict(finding_row)
        result = _apply_action(conn, finding, action, approved_by)
        now = _now()
        finding_status = 'ignored' if action['action_type'].startswith('ignore') else 'resolved'
        conn.execute(
            """UPDATE reconciliation_actions SET status = 'applied', approved_by = ?,
               result_json = ?, applied_at = ? WHERE id = ?""",
            (approved_by, _json(result), now, action_id),
        )
        conn.execute(
            "UPDATE reconciliation_findings SET status = ?, resolved_at = ?, resolved_by = ?, updated_at = ? WHERE id = ?",
            (finding_status, now, approved_by, now, finding['id']),
        )
        conn.execute(
            """UPDATE reconciliation_runs SET
               open_findings = (SELECT COUNT(*) FROM reconciliation_findings WHERE run_id = ? AND status IN ('open', 'accepted'))
               WHERE id = ?""",
            (finding['run_id'], finding['run_id']),
        )
        remaining = conn.execute("SELECT open_findings FROM reconciliation_runs WHERE id = ?", (finding['run_id'],)).fetchone()
        if remaining and int(remaining['open_findings'] or 0) == 0:
            conn.execute("UPDATE reconciliation_runs SET status = 'resolved', completed_at = ? WHERE id = ?", (now, finding['run_id']))
        conn.commit()
        return {'id': action_id, 'status': 'applied', 'result': result}
    except Exception as exc:
        conn.rollback()
        try:
            conn.execute(
                "UPDATE reconciliation_actions SET status = 'failed', approved_by = ?, error_message = ? WHERE id = ?",
                (approved_by, str(exc), action_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def reject_action(action_id: str, *, rejected_by: str, reason: str = '') -> dict:
    conn = get_db_connection()
    try:
        action = conn.execute("SELECT * FROM reconciliation_actions WHERE id = ?", (action_id,)).fetchone()
        if not action:
            raise ValueError('Action not found')
        if action['status'] != 'pending':
            raise ValueError(f"Action is already {action['status']}")
        now = _now()
        conn.execute(
            "UPDATE reconciliation_actions SET status = 'rejected', approved_by = ?, error_message = ?, applied_at = ? WHERE id = ?",
            (rejected_by, reason, now, action_id),
        )
        conn.execute(
            "UPDATE reconciliation_findings SET status = 'rejected', resolved_at = ?, resolved_by = ?, updated_at = ? WHERE id = ?",
            (now, rejected_by, now, action['finding_id']),
        )
        conn.commit()
        return {'id': action_id, 'status': 'rejected'}
    finally:
        conn.close()
