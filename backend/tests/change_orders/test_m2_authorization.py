from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import hashlib


def _actor(user: dict) -> dict:
    return {
        'id': user['user_id'],
        'user_id': user['user_id'],
        'username': user['username'],
        'role': user['role'],
        'tenant_id': user.get('tenant_id') or 'tenant-default',
    }


def _create_order(database, requester: dict, *, status: str, control_sheet: dict | None = None,
                  assigned_final_approver_id: str = '', implementer_id: str = '',
                  result_detail: dict | None = None, scheduled_start: str = '',
                  scheduled_end: str = '') -> dict:
    from services.change_order_service import create_change_order

    conn = database.get_db_connection()
    try:
        implementer_username = ''
        if implementer_id:
            implementer_row = conn.execute(
                'SELECT username FROM users WHERE id = ?', (implementer_id,),
            ).fetchone()
            implementer_username = str(implementer_row['username'] or '') if implementer_row else ''
        order = create_change_order(
            conn,
            title='M2 authorization fixture',
            description='fixture for focused backend authorization tests',
            status=status,
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id=requester.get('tenant_id') or 'tenant-default',
            assigned_initial_reviewer_id='',
            assigned_final_approver_id=assigned_final_approver_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            control_sheet={
                **(control_sheet or {}),
                **({'implementer': {'id': implementer_id, 'username': implementer_username}} if implementer_id else {}),
            },
            commit=False,
        )
        if result_detail is not None:
            conn.execute(
                'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
                (__import__('json').dumps(result_detail, ensure_ascii=False), order['id']),
            )
        conn.commit()
        return order
    finally:
        conn.close()


def _authorize_test_client(monkeypatch, actors: dict[str, dict]) -> TestClient:
    from api import users as users_api
    from main import app

    monkeypatch.setattr(users_api, 'validate_session_token', lambda token: actors.get(token))
    return TestClient(app)


def test_control_sheet_identity_compatibility_and_snapshot_scope():
    from api.change_orders.helpers import approval_snapshot_hash
    from services.change_order_service import (
        control_sheet_business_confirmer,
        control_sheet_implementer,
        normalize_control_sheet_identity,
    )

    normalized = normalize_control_sheet_identity({
        'implementer_id': 'executor-1',
        'implementer_username': 'executor',
        'business_verifier': {'id': 'verifier-1', 'username': 'verifier'},
        'business_verifier_id': 'legacy-verifier',
        'business_verify': '确认业务恢复',
        'execution': '切换接口参数',
    })
    assert normalized['implementer'] == {'id': 'executor-1', 'username': 'executor'}
    assert control_sheet_implementer(normalized)['id'] == 'executor-1'
    assert normalized['business_confirmer'] == {'id': 'verifier-1', 'username': 'verifier'}
    assert control_sheet_business_confirmer(normalized)['id'] == 'verifier-1'
    assert 'implementer_id' not in normalized
    assert 'business_verifier_id' not in normalized

    base_order = {
        'title': 'scope',
        'requester_id': 'requester-1',
        'assigned_initial_reviewer_id': 'reviewer-1',
        'assigned_final_approver_id': 'approver-1',
        'order_type': 'config_change',
        'scheduled_start': '2026-10-24T10:00',
        'scheduled_end': '2026-10-24T11:00',
        'target_devices': [{'id': 'device-1'}],
        'commands': ['interface ge-0/0/1', 'description uplink'],
        'rollback_plan': '恢复原描述',
        'command_template': {'scenario_id': 'scenario-1', 'preview': {'execute': ['interface ge-0/0/1']}},
        'control_sheet': normalized,
    }
    original_hash = approval_snapshot_hash(base_order)
    equivalent_offset_hash = approval_snapshot_hash({
        **base_order,
        'scheduled_start': '2026-10-24T10:00:00+08:00',
        'scheduled_end': '2026-10-24T11:00:00+08:00',
    })
    assert equivalent_offset_hash == original_hash
    assert approval_snapshot_hash({
        **base_order,
        'control_sheet': {**normalized, 'execution': '修改为其他命令'},
    }) != original_hash
    assert approval_snapshot_hash({
        **base_order,
        'control_sheet': {**normalized, 'implementer': {'id': 'executor-2', 'username': 'other'}},
    }) != original_hash
    attachment_order = {
        **base_order,
        'control_sheet_attachments': [
            {'id': 'att-2', 'file_name': 'b.pdf', 'file_size': 12, 'created_at': '2026-10-24T02:00:00Z', 'sha256': 'b'},
            {'id': 'att-1', 'file_name': 'a.pdf', 'file_size': 10, 'created_at': '2026-10-24T01:00:00Z', 'sha256': 'a'},
        ],
    }
    attachment_hash = approval_snapshot_hash(attachment_order)
    assert approval_snapshot_hash({
        **attachment_order,
        'control_sheet_attachments': list(reversed(attachment_order['control_sheet_attachments'])),
    }) == attachment_hash
    assert approval_snapshot_hash({
        **attachment_order,
        'control_sheet_attachments': [
            {**attachment_order['control_sheet_attachments'][0], 'sha256': 'changed'},
            attachment_order['control_sheet_attachments'][1],
        ],
    }) != attachment_hash


def test_attachment_metadata_and_content_hash_invalidate_approved_scope(
    isolated_db, make_user, monkeypatch, tmp_path,
):
    import json

    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services import change_order_service
    from services.change_order_service import create_change_order, get_change_order

    database = isolated_db['module']
    requester = make_user('m2-attachment-requester')
    implementer = make_user('m2-attachment-implementer')
    approver = make_user('m2-attachment-approver', role='Administrator', change_groups=['final_approver'])
    attachment_dir = tmp_path / 'data' / 'change_order_attachments'
    attachment_dir.mkdir(parents=True)
    attachment_path = attachment_dir / 'attachment-1.pdf'
    attachment_path.write_bytes(b'first-content')
    monkeypatch.setattr(change_order_service, 'PROJECT_ROOT', str(tmp_path))
    conn = database.get_db_connection()
    try:
        order = create_change_order(
            conn,
            title='Attachment approval scope',
            status='approved',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            control_sheet={'implementer': {'id': implementer['user_id'], 'username': implementer['username']}},
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        conn.execute(
            """INSERT INTO change_order_control_sheet_attachments
               (id, order_id, file_path, file_name, file_size, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ('attachment-1', order['id'], str(attachment_path), 'control.pdf', len(b'first-content'), '2026-10-24T02:00:00Z'),
        )
        conn.commit()
        approved_order = get_change_order(conn, order['id'])
        assert 'file_path' not in approved_order['control_sheet_attachments'][0]
        assert approved_order['control_sheet_attachments'][0]['sha256'] == hashlib.sha256(b'first-content').hexdigest()
        approved_hash = approval_snapshot_hash(approved_order)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': approved_hash,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            }), order['id']),
        )
        conn.commit()

        # The supported upload API uses a fresh generated name per attachment;
        # this same-path overwrite models an external storage mutation.
        attachment_path.write_bytes(b'other-content')
        changed_order = get_change_order(conn, order['id'])
        assert approval_snapshot_hash(changed_order) != approved_hash

        from api.change_orders.attachments import _record_attachment_scope_change
        _record_attachment_scope_change(
            conn,
            changed_order,
            _actor(requester),
            reason='control-sheet attachment added',
            occurred_at='2026-10-24T02:05:00Z',
        )
        conn.commit()
        reopened = get_change_order(conn, order['id'])
    finally:
        conn.close()
    assert reopened['status'] == 'initial_review'
    assert 'approval_snapshot_hash' not in reopened['result_detail']
    assert reopened['result_detail']['invalidated_approval_authorizations'][0]['authorization']['approval_snapshot_hash'] == approved_hash


def test_started_execution_blocks_control_sheet_and_regular_attachment_uploads(
    isolated_db, make_user, monkeypatch, tmp_path,
):
    import json

    from api.change_orders import attachments as attachments_api
    from services.change_order_service import get_change_order

    database = isolated_db['module']
    requester = make_user('m2-upload-requester')
    conn = database.get_db_connection()
    orders = []
    try:
        for status in ('implementing', 'executing'):
            order = _create_order(database, requester, status=status)
            conn.execute(
                'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
                (json.dumps({'execution_started_at': '2026-10-24T02:00:00Z'}), order['id']),
            )
            orders.append(order)
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(attachments_api, 'PROJECT_ROOT', str(tmp_path))
    client = _authorize_test_client(monkeypatch, {'upload-token': _actor(requester)})
    for order in orders:
        for suffix in ('control-sheet', 'attachments'):
            response = client.post(
                f"/api/change-orders/{order['id']}/{suffix}",
                headers={'Authorization': 'Bearer upload-token'},
                files={'file': ('scope.pdf', b'%PDF-1.4 attachment payload', 'application/pdf')},
            )
            assert response.status_code == 409, response.text
        read_conn = database.get_db_connection()
        try:
            current = get_change_order(read_conn, order['id'])
        finally:
            read_conn.close()
        assert current['status'] == order['status']
        assert current['result_detail']['execution_started_at'] == '2026-10-24T02:00:00Z'
        assert current['control_sheet_attachments'] == []
    assert not (tmp_path / 'data' / 'change_order_attachments').exists()


def test_change_window_uses_shanghai_for_naive_values_and_half_open_boundaries():
    from api.change_orders.helpers import assert_change_order_window_open

    start = '2026-10-24T10:00'
    end = '2026-10-24T11:00'
    assert assert_change_order_window_open(
        {'scheduled_start': start, 'scheduled_end': end},
        now=datetime(2026, 10, 24, 2, 30, tzinfo=timezone.utc),
    )
    assert assert_change_order_window_open(
        {
            'scheduled_start': '2026-10-24T10:00:00+08:00',
            'scheduled_end': '2026-10-24T03:00:00Z',
        },
        now=datetime(2026, 10, 24, 2, 30, tzinfo=timezone.utc),
    )
    with pytest.raises(HTTPException) as before_start:
        assert_change_order_window_open(
            {'scheduled_start': start, 'scheduled_end': end},
            now=datetime(2026, 10, 24, 1, 59, tzinfo=timezone.utc),
        )
    assert '尚未开始' in str(before_start.value.detail)
    with pytest.raises(HTTPException) as at_end:
        assert_change_order_window_open(
            {'scheduled_start': start, 'scheduled_end': end},
            now=datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc),
        )
    assert '已结束' in str(at_end.value.detail)
    with pytest.raises(HTTPException) as missing:
        assert_change_order_window_open({'scheduled_start': start, 'scheduled_end': ''})
    assert '缺失' in str(missing.value.detail)
    with pytest.raises(HTTPException) as invalid:
        assert_change_order_window_open({'scheduled_start': 'not-a-date', 'scheduled_end': end})
    assert '无效' in str(invalid.value.detail)


def test_approval_window_allows_before_or_during_window_but_rejects_expired_window():
    from api.change_orders.helpers import assert_change_order_window_approvable

    order = {'scheduled_start': '2026-10-24T10:00', 'scheduled_end': '2026-10-24T11:00'}
    before_start = datetime(2026, 10, 24, 1, 59, tzinfo=timezone.utc)
    during_window = datetime(2026, 10, 24, 2, 30, tzinfo=timezone.utc)
    at_end = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)

    assert assert_change_order_window_approvable(order, now=before_start)
    assert assert_change_order_window_approvable(order, now=during_window)
    with pytest.raises(HTTPException) as expired:
        assert_change_order_window_approvable(order, now=at_end)
    assert expired.value.status_code == 409
    assert '窗口已结束' in str(expired.value.detail)


def test_admin_role_alone_does_not_grant_device_execution():
    from api.change_orders.helpers import assert_explicit_execution_profile
    from core.rbac import authorize_resource, resource_action_allowed

    with pytest.raises(HTTPException) as denied:
        assert_explicit_execution_profile({'role': 'Administrator'}, 'command')
    assert denied.value.status_code == 403
    assert not resource_action_allowed(
        {'role': 'Administrator', 'role_profile': 'Change Requester'},
        'command',
        'execute',
    )
    assert not authorize_resource(
        {'role': 'Administrator', 'role_profile': 'Change Requester'},
        'command',
        'execute',
    )
    assert_explicit_execution_profile(
        {'role': 'Administrator', 'role_profile': 'Automation Operator'},
        'command',
    )
    assert authorize_resource(
        {'role': 'Administrator', 'role_profile': 'Automation Operator'},
        'command',
        'execute',
    )
    assert authorize_resource(
        {'role': 'Administrator', 'role_profile': 'System Administrator'},
        'command',
        'execute',
    )


def test_final_approval_does_not_require_implementer_command_execution_permission(
    isolated_db, make_user, monkeypatch,
):
    database = isolated_db['module']
    requester = make_user('approval-permission-requester')
    implementer = make_user('approval-permission-implementer', role='Administrator')
    approver = make_user(
        'approval-permission-approver',
        role='Administrator',
        change_groups=['final_approver'],
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    order = _create_order(
        database,
        requester,
        status='final_review',
        assigned_final_approver_id=approver['user_id'],
        implementer_id=implementer['user_id'],
        scheduled_start=(now - timedelta(minutes=1)).isoformat(),
        scheduled_end=(now + timedelta(days=1)).isoformat(),
    )
    client = _authorize_test_client(monkeypatch, {
        'approver-token': _actor(approver),
        'implementer-token': _actor(implementer),
    })

    approval = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer approver-token'},
        json={'status': 'approved'},
    )

    assert approval.status_code == 200, approval.text
    assert approval.json()['data']['status'] == 'approved'

    implementation = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'implementing'},
    )
    assert implementation.status_code == 403
    assert 'command.execute' in implementation.json()['detail']


def test_final_approver_cannot_be_the_implementer(isolated_db, make_user, monkeypatch):
    database = isolated_db['module']
    requester = make_user('approval-separation-requester')
    approver_and_implementer = make_user(
        'approval-separation-user',
        role='Administrator',
        change_groups=['final_approver'],
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    order = _create_order(
        database,
        requester,
        status='final_review',
        implementer_id=approver_and_implementer['user_id'],
        scheduled_start=(now - timedelta(minutes=1)).isoformat(),
        scheduled_end=(now + timedelta(days=1)).isoformat(),
    )
    client = _authorize_test_client(monkeypatch, {
        'combined-token': _actor(approver_and_implementer),
    })

    response = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer combined-token'},
        json={'status': 'approved'},
    )

    assert response.status_code == 403
    assert response.json()['detail'] == '终审人不能作为该工单的实施人'


def test_final_approval_rejects_expired_change_window(isolated_db, make_user, monkeypatch):
    database = isolated_db['module']
    requester = make_user('expired-window-requester')
    implementer = make_user('expired-window-implementer')
    approver = make_user(
        'expired-window-approver',
        role='Administrator',
        change_groups=['final_approver'],
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    order = _create_order(
        database,
        requester,
        status='final_review',
        assigned_final_approver_id=approver['user_id'],
        implementer_id=implementer['user_id'],
        scheduled_start=(now - timedelta(days=1)).isoformat(),
        scheduled_end=(now - timedelta(minutes=1)).isoformat(),
    )
    client = _authorize_test_client(monkeypatch, {
        'approver-token': _actor(approver),
    })

    response = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer approver-token'},
        json={'status': 'approved'},
    )

    assert response.status_code == 409
    assert '窗口已结束' in response.json()['detail']


def test_assignment_transfer_invalidates_approval_and_verification_gates_completion(
    isolated_db, make_user, monkeypatch,
):
    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import get_change_order, update_change_order

    database = isolated_db['module']
    requester = make_user('m2-requester')
    implementer = make_user('m2-implementer')
    replacement = make_user('m2-replacement')
    approver = make_user('m2-approver', role='Administrator', change_groups=['final_approver'])
    inactive = make_user('m2-inactive-target')
    verifier = make_user('m2-business-verifier')
    technical_verifier = make_user('m2-technical-verifier')

    approved_order = _create_order(
        database,
        requester,
        status='approved',
        assigned_final_approver_id=approver['user_id'],
        implementer_id=implementer['user_id'],
        control_sheet={'business_verify': '业务验证通过'},
    )
    conn = database.get_db_connection()
    try:
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], approved_order['id']),
        )
        order = get_change_order(conn, approved_order['id'])
        snapshot = approval_snapshot_hash(order)
        update_change_order(conn, approved_order['id'], {
            'result_detail': {
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
                'approved_at': '2026-10-24T02:00:00Z',
            },
        }, commit=True)
    finally:
        conn.close()

    token_actors = {
        'requester-token': _actor(requester),
        'implementer-token': _actor(implementer),
        'replacement-token': _actor(replacement),
        'approver-token': _actor(approver),
        'verifier-token': _actor(verifier),
        'technical-token': _actor(technical_verifier),
    }
    client = _authorize_test_client(monkeypatch, token_actors)
    final_approver_assignment = client.post(
        f"/api/change-orders/{approved_order['id']}/assignment",
        headers={'Authorization': 'Bearer requester-token'},
        json={'action': 'assign', 'implementer_id': approver['user_id']},
    )
    assert final_approver_assignment.status_code == 400
    conn = database.get_db_connection()
    try:
        conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (inactive['user_id'],))
        conn.commit()
    finally:
        conn.close()
    inactive_assignment = client.post(
        f"/api/change-orders/{approved_order['id']}/assignment",
        headers={'Authorization': 'Bearer requester-token'},
        json={'action': 'assign', 'implementer_id': inactive['user_id']},
    )
    assert inactive_assignment.status_code == 400
    transfer_without_reason = client.post(
        f"/api/change-orders/{approved_order['id']}/assignment",
        headers={'Authorization': 'Bearer requester-token'},
        json={'action': 'transfer', 'implementer_id': replacement['user_id']},
    )
    assert transfer_without_reason.status_code == 400
    final_approver_execution = client.post(
        f"/api/change-orders/{approved_order['id']}/transition",
        headers={'Authorization': 'Bearer approver-token'},
        json={'status': 'implementing'},
    )
    assert final_approver_execution.status_code == 403
    transfer = client.post(
        f"/api/change-orders/{approved_order['id']}/assignment",
        headers={'Authorization': 'Bearer requester-token'},
        json={'action': 'transfer', 'implementer_id': replacement['user_id'], 'reason': '轮值交接'},
    )
    assert transfer.status_code == 200, transfer.text
    transferred = transfer.json()['data']
    assert transferred['status'] == 'initial_review'
    assert transferred['control_sheet']['implementer']['id'] == replacement['user_id']
    transfer_event = transferred['result_detail']['assignment_events'][-1]
    assert transfer_event == {
        'action': 'transfer',
        'actor_id': requester['user_id'],
        'actor_username': requester['username'],
        'from_implementer_id': implementer['user_id'],
        'from_username': implementer['username'],
        'to_implementer_id': replacement['user_id'],
        'to_username': replacement['username'],
        'implementer_id': replacement['user_id'],
        'implementer_username': replacement['username'],
        'reason': '轮值交接',
        'created_at': transfer_event['created_at'],
    }
    assert transferred['result_detail']['invalidated_approval_authorizations'][0]['authorization']['approval_snapshot_hash'] == snapshot
    assert 'approval_snapshot_hash' not in transferred['result_detail']

    implementing_order = _create_order(
        database,
        requester,
        status='implementing',
        assigned_final_approver_id=approver['user_id'],
        implementer_id=implementer['user_id'],
        control_sheet={
            'business_verify': '业务确认',
            'business_verifier_id': verifier['user_id'],
            'business_verifier_username': verifier['username'],
        },
    )
    conn = database.get_db_connection()
    try:
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], implementing_order['id']),
        )
        order = get_change_order(conn, implementing_order['id'])
        snapshot = approval_snapshot_hash(order)
        update_change_order(conn, implementing_order['id'], {
            'result_detail': {
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            },
        }, commit=True)
    finally:
        conn.close()

    denied_technical = client.post(
        f"/api/change-orders/{implementing_order['id']}/verification",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'kind': 'technical', 'result': 'passed', 'summary': '不能自验'},
    )
    assert denied_technical.status_code == 403
    technical = client.post(
        f"/api/change-orders/{implementing_order['id']}/verification",
        headers={'Authorization': 'Bearer technical-token'},
        json={'kind': 'technical', 'result': 'passed', 'summary': '技术检查通过', 'evidence': ['show output']},
    )
    assert technical.status_code == 200, technical.text
    denied_business = client.post(
        f"/api/change-orders/{implementing_order['id']}/verification",
        headers={'Authorization': 'Bearer requester-token'},
        json={'kind': 'business', 'result': 'passed', 'summary': '申请人不能绕开指定确认人'},
    )
    assert denied_business.status_code == 403
    failed_business = client.post(
        f"/api/change-orders/{implementing_order['id']}/verification",
        headers={'Authorization': 'Bearer verifier-token'},
        json={'kind': 'business', 'result': 'failed', 'summary': '业务结果仍不正确'},
    )
    assert failed_business.status_code == 200, failed_business.text
    premature_complete = client.post(
        f"/api/change-orders/{implementing_order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'completed'},
    )
    assert premature_complete.status_code == 409
    passed_business = client.post(
        f"/api/change-orders/{implementing_order['id']}/verification",
        headers={'Authorization': 'Bearer verifier-token'},
        json={'kind': 'business', 'result': 'passed', 'summary': '业务结果确认'},
    )
    assert passed_business.status_code == 200, passed_business.text
    completed = client.post(
        f"/api/change-orders/{implementing_order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'completed', 'result_summary': '技术与业务验证通过'},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()['data']['status'] == 'completed'


def test_rolled_back_requires_new_post_rollback_verification(isolated_db, make_user, monkeypatch):
    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import get_change_order, update_change_order

    database = isolated_db['module']
    requester = make_user('m2-rollback-requester')
    implementer = make_user('m2-rollback-implementer')
    approver = make_user('m2-rollback-approver', role='Administrator', change_groups=['final_approver'])
    confirmer = make_user('m2-rollback-confirmer')
    verifier = make_user('m2-rollback-technical')
    rollback_started_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat()
    order = _create_order(
        database,
        requester,
        status='rollback_in_progress',
        assigned_final_approver_id=approver['user_id'],
        implementer_id=implementer['user_id'],
        control_sheet={
            'business_verify': '回退后业务恢复确认',
            'business_confirmer': {'id': confirmer['user_id'], 'username': confirmer['username']},
        },
    )
    conn = database.get_db_connection()
    try:
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        old_record_time = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
        update_change_order(conn, order['id'], {
            'result_detail': {
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
                'rollback_started_at': rollback_started_at,
                'verification_records': [
                    {
                        'kind': 'technical', 'result': 'passed', 'created_at': old_record_time,
                        'approval_snapshot_hash': snapshot,
                    },
                    {
                        'kind': 'business', 'result': 'passed', 'created_at': old_record_time,
                        'approval_snapshot_hash': snapshot,
                    },
                ],
            },
        }, commit=True)
    finally:
        conn.close()

    actors = {
        'implementer-token': _actor(implementer),
        'confirmer-token': _actor(confirmer),
        'verifier-token': _actor(verifier),
    }
    client = _authorize_test_client(monkeypatch, actors)
    stale_verification = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'rolled_back'},
    )
    assert stale_verification.status_code == 409

    technical = client.post(
        f"/api/change-orders/{order['id']}/verification",
        headers={'Authorization': 'Bearer verifier-token'},
        json={'kind': 'technical', 'result': 'failed', 'summary': '回退后链路仍异常'},
    )
    assert technical.status_code == 200, technical.text
    failed_restore = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'rolled_back'},
    )
    assert failed_restore.status_code == 409

    passed_technical = client.post(
        f"/api/change-orders/{order['id']}/verification",
        headers={'Authorization': 'Bearer verifier-token'},
        json={'kind': 'technical', 'result': 'passed', 'summary': '回退配置与接口状态均恢复'},
    )
    passed_business = client.post(
        f"/api/change-orders/{order['id']}/verification",
        headers={'Authorization': 'Bearer confirmer-token'},
        json={'kind': 'business', 'result': 'passed', 'summary': '业务恢复确认'},
    )
    assert passed_technical.status_code == 200, passed_technical.text
    assert passed_business.status_code == 200, passed_business.text
    rolled_back = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={'Authorization': 'Bearer implementer-token'},
        json={'status': 'rolled_back', 'result_summary': '回退恢复验证通过'},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()['data']['status'] == 'rolled_back'


def test_named_business_confirmer_can_view_single_order_verify_but_not_edit_or_assign(
    isolated_db, make_user, monkeypatch,
):
    import json

    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import create_change_order, get_change_order

    database = isolated_db['module']
    requester = make_user('m2-view-requester')
    implementer = make_user('m2-view-implementer')
    approver = make_user('m2-view-approver', role='Administrator', change_groups=['final_approver'])
    confirmer = make_user('m2-view-business-confirmer', role='Viewer')
    conn = database.get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET role_profile = 'Change Requester', scope_mode = 'restricted' WHERE id = ?",
            (confirmer['user_id'],),
        )
        for resource_type, actions in (
            ('pam', ['view']),
            ('change_order', ['view']),
        ):
            conn.execute(
                """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, ?, 'tenant', 'tenant-default', ?, '2026-10-24T00:00:00Z')""",
                (f"m2-{confirmer['user_id']}-{resource_type}", confirmer['user_id'], resource_type, json.dumps(actions)),
            )
        order = create_change_order(
            conn,
            title='Named business confirmer access',
            status='implementing',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            control_sheet={
                'implementer': {'id': implementer['user_id'], 'username': implementer['username']},
                'business_verify': '业务结果验收',
                'business_confirmer': {'id': confirmer['user_id'], 'username': confirmer['username']},
            },
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            }), order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    confirmer_actor = {**_actor(confirmer), 'role_profile': 'Change Requester'}
    client = _authorize_test_client(monkeypatch, {'confirmer-token': confirmer_actor})
    get_response = client.get(
        f"/api/change-orders/{order['id']}",
        headers={'Authorization': 'Bearer confirmer-token'},
    )
    assert get_response.status_code == 200, get_response.text
    todo_response = client.get(
        '/api/change-orders?my_todo_kind=business_verification',
        headers={'Authorization': 'Bearer confirmer-token'},
    )
    assert todo_response.status_code == 200, todo_response.text
    assert [item['id'] for item in todo_response.json()['data']] == [order['id']]
    assert todo_response.json()['data'][0]['todo_kind'] == 'business_verification'
    default_todo = client.get(
        f"/api/change-orders?my_todo={confirmer['username']}",
        headers={'Authorization': 'Bearer confirmer-token'},
    )
    assert default_todo.status_code == 200, default_todo.text
    assert [item['id'] for item in default_todo.json()['data']] == [order['id']]
    assert default_todo.json()['data'][0]['todo_kind'] == 'business_verification'
    from services.change_order_service import get_summary
    conn = database.get_db_connection()
    try:
        confirmer_summary = get_summary(
            conn,
            user_id=confirmer['user_id'],
            username=confirmer['username'],
            tenant_id='tenant-default',
            requester_id=confirmer['user_id'],
        )
    finally:
        conn.close()
    assert confirmer_summary['my_todo_count'] == 1

    edit_response = client.put(
        f"/api/change-orders/{order['id']}",
        headers={'Authorization': 'Bearer confirmer-token'},
        json={'title': 'unauthorized edit'},
    )
    assert edit_response.status_code == 404
    assignment_response = client.post(
        f"/api/change-orders/{order['id']}/assignment",
        headers={'Authorization': 'Bearer confirmer-token'},
        json={'action': 'transfer', 'implementer_id': implementer['user_id'], 'reason': 'not allowed'},
    )
    assert assignment_response.status_code == 404

    verification_response = client.post(
        f"/api/change-orders/{order['id']}/verification",
        headers={'Authorization': 'Bearer confirmer-token'},
        json={'kind': 'business', 'result': 'passed', 'summary': '指定业务确认人验收通过'},
    )
    assert verification_response.status_code == 200, verification_response.text


@pytest.mark.parametrize(
    'legacy_identity',
    [
        'nested_business_verifier_username',
        'flat_business_verifier_username',
    ],
)
def test_legacy_username_only_business_confirmer_can_view_and_verify(
    isolated_db, make_user, monkeypatch, legacy_identity,
):
    import json

    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import create_change_order, get_change_order

    database = isolated_db['module']
    requester = make_user(f'm2-legacy-requester-{legacy_identity}')
    implementer = make_user(f'm2-legacy-implementer-{legacy_identity}')
    approver = make_user(f'm2-legacy-approver-{legacy_identity}', role='Administrator', change_groups=['final_approver'])
    confirmer = make_user(f'm2-legacy-confirmer-{legacy_identity}', role='Viewer')
    conn = database.get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET role_profile = 'Change Requester', scope_mode = 'restricted' WHERE id = ?",
            (confirmer['user_id'],),
        )
        for resource_type in ('pam', 'change_order'):
            conn.execute(
                """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, ?, 'tenant', 'tenant-default', '[\"view\"]', '2026-10-24T00:00:00Z')""",
                (f"legacy-{confirmer['user_id']}-{resource_type}", confirmer['user_id'], resource_type),
            )
        control_sheet = {'business_verify': '业务确认'}
        if legacy_identity == 'nested_business_verifier_username':
            control_sheet['business_verifier'] = {'username': confirmer['username']}
        else:
            control_sheet['business_verifier_username'] = confirmer['username']
        order = create_change_order(
            conn,
            title='Legacy business confirmer compatibility',
            status='implementing',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            control_sheet={
                **control_sheet,
                'implementer': {'id': implementer['user_id'], 'username': implementer['username']},
            },
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            }), order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    confirmer_actor = {**_actor(confirmer), 'role_profile': 'Change Requester'}
    client = _authorize_test_client(monkeypatch, {'legacy-confirmer-token': confirmer_actor})
    detail = client.get(
        f"/api/change-orders/{order['id']}",
        headers={'Authorization': 'Bearer legacy-confirmer-token'},
    )
    assert detail.status_code == 200, detail.text
    verification = client.post(
        f"/api/change-orders/{order['id']}/verification",
        headers={'Authorization': 'Bearer legacy-confirmer-token'},
        json={'kind': 'business', 'result': 'passed', 'summary': '历史用户名确认人通过'},
    )
    assert verification.status_code == 200, verification.text


def test_independent_implementer_owns_todo_assignee_and_summary_count(isolated_db, make_user, monkeypatch):
    from services.change_order_service import get_summary

    database = isolated_db['module']
    requester = make_user('m2-queue-requester')
    implementer = make_user('m2-queue-implementer')
    assigned_order = _create_order(
        database,
        requester,
        status='implementing',
        implementer_id=implementer['user_id'],
    )
    # Legacy tickets without an implementation identity still remain in the
    # original requester's implementation queue.
    legacy_order = _create_order(database, implementer, status='approved')
    client = _authorize_test_client(monkeypatch, {'queue-token': _actor(implementer)})

    todo = client.get(
        f"/api/change-orders?my_todo={implementer['username']}&my_todo_kind=implement",
        headers={'Authorization': 'Bearer queue-token'},
    )
    assert todo.status_code == 200, todo.text
    assert {item['id'] for item in todo.json()['data']} == {assigned_order['id'], legacy_order['id']}
    assert all(item['todo_kind'] == 'implement' for item in todo.json()['data'])

    assignee = client.get(
        f"/api/change-orders?assignee={implementer['username']}",
        headers={'Authorization': 'Bearer queue-token'},
    )
    assert assignee.status_code == 200, assignee.text
    assert assigned_order['id'] in {item['id'] for item in assignee.json()['data']}

    conn = database.get_db_connection()
    try:
        summary = get_summary(
            conn,
            user_id=implementer['user_id'],
            username=implementer['username'],
            tenant_id='tenant-default',
        )
    finally:
        conn.close()
    assert summary['my_todo_count'] == 2


def test_published_playbook_version_without_scenario_still_consumes_linked_order_scope(
    isolated_db, make_user, monkeypatch,
):
    import json

    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import create_change_order, get_change_order
    from api.playbooks import routes as playbook_routes

    database = isolated_db['module']
    requester = make_user('m2-playbook-requester')
    implementer = make_user('m2-playbook-implementer')
    approver = make_user('m2-playbook-approver', role='Administrator', change_groups=['final_approver'])
    conn = database.get_db_connection()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    phases = {
        'pre_check': [],
        'execute': ['interface GigabitEthernet0/1', 'description approved'],
        'post_check': [],
        'rollback': [],
    }
    try:
        conn.execute(
            'INSERT INTO devices (id, hostname, platform, tenant_id, status) VALUES (?, ?, ?, ?, ?)',
            ('m2-playbook-device', 'edge-m2', 'cisco_ios', 'tenant-default', 'online'),
        )
        order = create_change_order(
            conn,
            title='Published Playbook authorization',
            status='implementing',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            target_devices=[{'id': 'm2-playbook-device'}],
            commands=phases['execute'] + ['write memory'],
            scheduled_start=(now - timedelta(minutes=5)).isoformat(),
            scheduled_end=(now + timedelta(minutes=10)).isoformat(),
            control_sheet={'implementer': {'id': implementer['user_id'], 'username': implementer['username']}},
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
                'executing_snapshot_hash': snapshot,
                'execution_token_id': 'm2-playbook-token',
                'execution_token_consumed_at': now.isoformat(),
                'mfa_verified_at': now.isoformat(),
                'mfa_verified_by_id': implementer['user_id'],
                'mfa_verified_by': implementer['username'],
            }), order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    actors = {'playbook-token': _actor(implementer)}
    client = _authorize_test_client(monkeypatch, actors)
    selected_version = {
        'id': 'published-version-m2',
        'playbook_id': 'published-playbook-m2',
        'tenant_id': 'tenant-default',
        'status': 'PUBLISHED',
        'name': 'Published configuration Playbook',
        'definition': {'platform': 'cisco_ios', 'risk': 'low', 'phases': phases},
    }
    monkeypatch.setattr(
        playbook_routes,
        '_call_playbook_version',
        lambda _fn, *_args, **_kwargs: selected_version,
    )
    monkeypatch.setattr(playbook_routes, '_ensure_controlled_phases', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(playbook_routes, '_run_playbook', lambda *_args, **_kwargs: _async_noop())

    response = client.post(
        '/api/playbooks/execute',
        headers={'Authorization': 'Bearer playbook-token'},
        json={
            'playbook_version_id': selected_version['id'],
            # Deliberately omit scenario_id: this is the former scenario=None bypass.
            'device_ids': ['m2-playbook-device'],
            'variables': {},
            'platform': 'cisco_ios',
            'change_ticket': order['order_number'],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()['change_order_number'] == order['order_number']
    conn = database.get_db_connection()
    try:
        detail_row = conn.execute(
            'SELECT result_detail_json FROM change_orders WHERE id = ?', (order['id'],),
        ).fetchone()
    finally:
        conn.close()
    detail = json.loads(detail_row['result_detail_json'])
    assert detail['execution_started_by'] == implementer['user_id']
    assert detail['execution_request_hash']
    assert detail['playbook_execution_events'][-1]['status'] == 'queued'


def test_direct_execute_reports_partial_failure_and_keeps_order_implementing(isolated_db, make_user, monkeypatch):
    import json

    from api import automation
    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import create_change_order, get_change_order

    database = isolated_db['module']
    requester = make_user('m2-direct-requester')
    implementer = make_user('m2-direct-implementer')
    approver = make_user('m2-direct-approver', role='Administrator', change_groups=['final_approver'])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    command = 'interface GigabitEthernet0/2'
    conn = database.get_db_connection()
    try:
        conn.execute(
            'INSERT INTO devices (id, hostname, platform, tenant_id, status) VALUES (?, ?, ?, ?, ?)',
            ('m2-direct-device', 'edge-direct', 'cisco_ios', 'tenant-default', 'online'),
        )
        order = create_change_order(
            conn,
            title='Direct execution result contract',
            status='implementing',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            target_devices=[{'id': 'm2-direct-device'}],
            commands=[command],
            rollback_plan='恢复原接口配置',
            scheduled_start=(now - timedelta(minutes=5)).isoformat(),
            scheduled_end=(now + timedelta(minutes=10)).isoformat(),
            control_sheet={'implementer': {'id': implementer['user_id'], 'username': implementer['username']}},
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
                'executing_snapshot_hash': snapshot,
                'execution_token_id': 'm2-direct-single-use-token',
                'execution_token_consumed_at': now.isoformat(),
                'mfa_verified_at': now.isoformat(),
                'mfa_verified_by_id': implementer['user_id'],
                'mfa_verified_by': implementer['username'],
            }), order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    class _FailedService:
        def execute_commands(self, *_args, **_kwargs):
            return [{'success': False, 'error': 'synthetic command failure'}]

    monkeypatch.setattr(automation, '_resolve_execution_credentials', lambda *_args, **_kwargs: {
        'username': 'operator', 'password': '', 'enable_password': '', 'resolved_role': 'normal',
    })
    monkeypatch.setattr(automation, 'AutomationService', _FailedService)
    monkeypatch.setattr(automation, '_record_instant_execution', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(automation, 'log_audit_event', lambda *_args, **_kwargs: None)
    client = _authorize_test_client(monkeypatch, {'direct-token': _actor(implementer)})
    response = client.post(
        '/api/execute',
        headers={'Authorization': 'Bearer direct-token'},
        json={
            'device_ids': ['m2-direct-device'],
            'command': [command],
            'isConfig': True,
            'change_ticket': order['order_number'],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'partial_failure'
    assert response.json()['results']['m2-direct-device']['status'] == 'failed'
    duplicate = client.post(
        '/api/execute',
        headers={'Authorization': 'Bearer direct-token'},
        json={
            'device_ids': ['m2-direct-device'],
            'command': [command],
            'isConfig': True,
            'change_ticket': order['order_number'],
        },
    )
    assert duplicate.status_code == 409
    conn = database.get_db_connection()
    try:
        updated = get_change_order(conn, order['id'])
    finally:
        conn.close()
    assert updated['status'] == 'implementing'
    assert updated['result_detail']['execution_results'][-1]['status'] == 'partial_failure'


def test_implementing_transition_requires_valid_mfa_and_records_stable_identity(
    isolated_db, make_user, monkeypatch,
):
    import json

    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    from services.change_order_service import create_change_order, get_change_order
    from backend.tests.conftest import current_test_totp

    database = isolated_db['module']
    requester = make_user('m2-mfa-requester')
    implementer = make_user('m2-mfa-implementer', mfa_enabled=True)
    approver = make_user('m2-mfa-approver', role='Administrator', change_groups=['final_approver'])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn = database.get_db_connection()
    try:
        conn.execute(
            'INSERT INTO devices (id, hostname, platform, tenant_id, status) VALUES (?, ?, ?, ?, ?)',
            ('m2-mfa-device', 'edge-mfa', 'cisco_ios', 'tenant-default', 'online'),
        )
        order = create_change_order(
            conn,
            title='MFA implementation start',
            status='approved',
            requester_id=requester['user_id'],
            requester_username=requester['username'],
            tenant_id='tenant-default',
            assigned_final_approver_id=approver['user_id'],
            target_devices=[{'id': 'm2-mfa-device'}],
            commands=['interface GigabitEthernet0/3'],
            rollback_plan='恢复原配置',
            scheduled_start=(now - timedelta(minutes=5)).isoformat(),
            scheduled_end=(now + timedelta(minutes=10)).isoformat(),
            control_sheet={'implementer': {'id': implementer['user_id'], 'username': implementer['username']}},
            commit=False,
        )
        conn.execute(
            'UPDATE change_orders SET final_approver_id = ?, approver_id = ? WHERE id = ?',
            (approver['user_id'], approver['user_id'], order['id']),
        )
        current = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(current)
        conn.execute(
            'UPDATE change_orders SET result_detail_json = ? WHERE id = ?',
            (json.dumps({
                'approval_snapshot_hash': snapshot,
                'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            }), order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    from api import change_orders as change_orders_api
    monkeypatch.setattr(change_orders_api, 'FEATURE_CONTROL_SHEET', False)
    client = _authorize_test_client(monkeypatch, {'mfa-token': _actor(implementer)})
    path = f"/api/change-orders/{order['id']}/transition"
    missing_code = client.post(
        path,
        headers={'Authorization': 'Bearer mfa-token'},
        json={'status': 'implementing'},
    )
    assert missing_code.status_code == 400
    invalid_code = client.post(
        path,
        headers={'Authorization': 'Bearer mfa-token'},
        json={'status': 'implementing', 'mfa_code': 'not-a-code'},
    )
    assert invalid_code.status_code == 403
    started = client.post(
        path,
        headers={'Authorization': 'Bearer mfa-token'},
        json={'status': 'implementing', 'mfa_code': current_test_totp(implementer['mfa_secret'])},
    )
    assert started.status_code == 200, started.text
    detail = started.json()['data']['result_detail']
    assert detail['mfa_verified_by_id'] == implementer['user_id']
    assert detail['mfa_verified_by'] == implementer['username']
    assert detail['approval_snapshot_version'] == APPROVAL_SNAPSHOT_VERSION


def test_concurrent_initial_review_actions_commit_only_one_transition(
    isolated_db, make_user, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    database = isolated_db['module']
    requester = make_user('m2-race-requester')
    reviewer = make_user('m2-race-reviewer', role='Administrator', change_groups=['initial_reviewer'])
    approver = make_user('m2-race-approver', role='Administrator', change_groups=['final_approver'])
    order = _create_order(database, requester, status='initial_review')
    conn = database.get_db_connection()
    try:
        conn.execute(
            'UPDATE change_orders SET assigned_initial_reviewer_id = ?, assigned_initial_reviewer_username = ? WHERE id = ?',
            (reviewer['user_id'], reviewer['username'], order['id']),
        )
        conn.commit()
    finally:
        conn.close()

    client = _authorize_test_client(monkeypatch, {'review-token': _actor(reviewer)})
    barrier = Barrier(3)

    def submit_review():
        barrier.wait(timeout=10)
        return client.post(
            f"/api/change-orders/{order['id']}/transition",
            headers={'Authorization': 'Bearer review-token'},
            json={'status': 'final_review', 'assigned_final_approver_id': approver['user_id']},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit_review) for _ in range(2)]
        barrier.wait(timeout=10)
        responses = [future.result(timeout=30) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 400]
    conn = database.get_db_connection()
    try:
        from services.change_order_service import get_change_order
        final_order = get_change_order(conn, order['id'])
    finally:
        conn.close()
    assert final_order['status'] == 'final_review'
    assert final_order['initial_reviewer_id'] == reviewer['user_id']
    assert final_order['assigned_final_approver_id'] == approver['user_id']


async def _async_noop():
    return None
