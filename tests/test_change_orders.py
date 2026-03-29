from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / 'backend'
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import api.change_orders as change_orders_api
import core.rbac as rbac
import services.audit_service as audit_service


def _init_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            '''
            CREATE TABLE change_orders (
                id TEXT PRIMARY KEY,
                order_number TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                order_type TEXT NOT NULL DEFAULT 'config_change',
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'draft',
                requester_id TEXT DEFAULT '',
                requester_username TEXT DEFAULT '',
                assigned_initial_reviewer_id TEXT DEFAULT '',
                assigned_initial_reviewer_username TEXT DEFAULT '',
                assigned_final_approver_id TEXT DEFAULT '',
                assigned_final_approver_username TEXT DEFAULT '',
                command_template_json TEXT DEFAULT '{}',
                initial_reviewer_id TEXT DEFAULT '',
                initial_reviewer_username TEXT DEFAULT '',
                approver_id TEXT DEFAULT '',
                approver_username TEXT DEFAULT '',
                final_approver_id TEXT DEFAULT '',
                final_approver_username TEXT DEFAULT '',
                target_devices_json TEXT DEFAULT '[]',
                commands_json TEXT DEFAULT '[]',
                rollback_plan TEXT DEFAULT '',
                risk_level TEXT DEFAULT 'low',
                scheduled_start TEXT DEFAULT '',
                scheduled_end TEXT DEFAULT '',
                actual_start TEXT DEFAULT '',
                actual_end TEXT DEFAULT '',
                result_summary TEXT DEFAULT '',
                result_detail_json TEXT DEFAULT '{}',
                approval_token TEXT DEFAULT '',
                rejected_reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE audit_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                actor_id TEXT,
                actor_username TEXT,
                actor_role TEXT,
                source_ip TEXT,
                target_type TEXT,
                target_id TEXT,
                target_name TEXT,
                device_id TEXT,
                job_id TEXT,
                execution_id TEXT,
                snapshot_id TEXT,
                summary TEXT NOT NULL,
                details_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE,
                role TEXT,
                change_groups_json TEXT DEFAULT '[]'
            );

            CREATE TABLE custom_scenarios (
                id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                created_by TEXT DEFAULT 'admin',
                created_at TEXT,
                updated_at TEXT
            );
            '''
        )
        conn.executemany(
            'INSERT INTO users (id, username, role, change_groups_json) VALUES (?, ?, ?, ?)',
            [
                ('u-1', 'alice', 'Operator', '["requester"]'),
                ('u-2', 'bob', 'Operator', '["initial_reviewer"]'),
                ('u-3', 'admin', 'Administrator', '["final_approver"]'),
                ('u-4', 'carol', 'Operator', '["initial_reviewer"]'),
                ('u-5', 'dave', 'Administrator', '["final_approver"]'),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _auth_headers(username: str, role: str, user_id: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {username}|{role}|{user_id}'}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db_path = tmp_path / 'change_orders_test.db'
    _init_test_db(db_path)

    def test_get_db_connection() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def fake_current_user(request) -> dict | None:
        auth = request.headers.get('Authorization', '')
        token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
        if not token:
            return None
        username, role, user_id = token.split('|', 2)
        return {
            'username': username,
            'role': role,
            'user_id': user_id,
            'id': user_id,
        }

    monkeypatch.setattr(change_orders_api, 'get_db_connection', test_get_db_connection)
    monkeypatch.setattr(audit_service, 'get_db_connection', test_get_db_connection)
    monkeypatch.setattr(rbac, '_get_current_user', fake_current_user)

    app = FastAPI()
    app.include_router(change_orders_api.router, prefix='/api')
    with TestClient(app) as test_client:
        yield test_client


def _create_order(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    response = client.post(
        '/api/change-orders',
        headers=headers,
        json={
            'title': '核心交换机变更',
            'description': '调整接入口 VLAN',
            'order_type': 'config_change',
            'priority': 'high',
            'target_devices': [{'hostname': 'core-sw-01', 'ip_address': '10.0.0.1'}],
            'commands': ['interface vlan 100', 'description change-window'],
            'rollback_plan': '恢复原配置',
            'risk_level': 'medium',
            'scheduled_start': '',
            'scheduled_end': '',
            **overrides,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['success'] is True
    return payload['data']


def _transition(client: TestClient, order_id: str, headers: dict[str, str], status: str, **extra) -> dict:
    response = client.post(
        f'/api/change-orders/{order_id}/transition',
        headers=headers,
        json={'status': status, **extra},
    )
    return response


def test_change_order_happy_path_and_timeline(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')
    reviewer_headers = _auth_headers('bob', 'Operator', 'u-2')
    admin_headers = _auth_headers('admin', 'Administrator', 'u-3')

    order = _create_order(client, requester_headers)
    order_id = order['id']
    assert order['status'] == 'draft'

    assert _transition(client, order_id, requester_headers, 'initial_review').status_code == 200

    response = _transition(client, order_id, reviewer_headers, 'final_review')
    assert response.status_code == 200
    assert response.json()['data']['initial_reviewer_username'] == 'bob'

    response = _transition(client, order_id, admin_headers, 'approved')
    assert response.status_code == 200
    approved_order = response.json()['data']
    assert approved_order['final_approver_username'] == 'admin'
    assert approved_order['approver_username'] == 'admin'

    assert _transition(client, order_id, requester_headers, 'implementing').status_code == 200

    response = _transition(
        client,
        order_id,
        requester_headers,
        'completed',
        result_summary='实施完成，业务恢复正常',
    )
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'completed'

    timeline_response = client.get(f'/api/change-orders/{order_id}/timeline', headers=requester_headers)
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()['data']
    assert [item['event_type'] for item in timeline] == [
        'change_order.created',
        'change_order.initial_review',
        'change_order.final_review',
        'change_order.approved',
        'change_order.implementing',
        'change_order.completed',
    ]


def test_requester_cannot_review_own_change_order(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')

    order = _create_order(client, requester_headers)
    order_id = order['id']

    assert _transition(client, order_id, requester_headers, 'initial_review').status_code == 200

    response = _transition(client, order_id, requester_headers, 'final_review')
    assert response.status_code == 403
    assert 'Requester cannot review/approve own change order' in response.json()['detail']


def test_final_approval_requires_administrator(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')
    reviewer_headers = _auth_headers('bob', 'Operator', 'u-2')

    order = _create_order(client, requester_headers)
    order_id = order['id']

    assert _transition(client, order_id, requester_headers, 'initial_review').status_code == 200
    assert _transition(client, order_id, reviewer_headers, 'final_review').status_code == 200

    response = _transition(client, order_id, reviewer_headers, 'approved')
    assert response.status_code == 403
    assert 'Only Administrator can finalize approval for change orders' in response.json()['detail']


def test_change_order_rollback_flow_records_reason(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')
    reviewer_headers = _auth_headers('bob', 'Operator', 'u-2')
    admin_headers = _auth_headers('admin', 'Administrator', 'u-3')

    order = _create_order(client, requester_headers)
    order_id = order['id']

    assert _transition(client, order_id, requester_headers, 'initial_review').status_code == 200
    assert _transition(client, order_id, reviewer_headers, 'final_review').status_code == 200
    assert _transition(client, order_id, admin_headers, 'approved').status_code == 200
    assert _transition(client, order_id, requester_headers, 'implementing').status_code == 200

    response = _transition(
        client,
        order_id,
        requester_headers,
        'rollback_in_progress',
        rollback_reason='验证发现业务异常，执行回退',
    )
    assert response.status_code == 200
    assert response.json()['data']['result_detail']['rollback_reason'] == '验证发现业务异常，执行回退'

    response = _transition(
        client,
        order_id,
        requester_headers,
        'rolled_back',
        result_summary='配置已回退，业务恢复',
    )
    assert response.status_code == 200
    rolled_back_order = response.json()['data']
    assert rolled_back_order['status'] == 'rolled_back'
    assert rolled_back_order['result_detail']['rollback_completed_at']
    assert rolled_back_order['result_summary'] == '配置已回退，业务恢复'

    timeline = client.get(f'/api/change-orders/{order_id}/timeline', headers=requester_headers).json()['data']
    assert [item['event_type'] for item in timeline][-2:] == [
        'change_order.rollback_in_progress',
        'change_order.rolled_back',
    ]


def test_assigned_reviewer_and_approver_are_enforced(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')
    assigned_reviewer_headers = _auth_headers('bob', 'Operator', 'u-2')
    assigned_admin_headers = _auth_headers('admin', 'Administrator', 'u-3')
    other_reviewer_headers = _auth_headers('carol', 'Operator', 'u-4')
    other_admin_headers = _auth_headers('dave', 'Administrator', 'u-5')

    order = _create_order(
        client,
        requester_headers,
        assigned_initial_reviewer_id='u-2',
        assigned_final_approver_id='u-3',
    )
    order_id = order['id']

    assert _transition(client, order_id, requester_headers, 'initial_review').status_code == 200

    response = _transition(client, order_id, other_reviewer_headers, 'final_review')
    assert response.status_code == 403
    assert 'assigned initial reviewer' in response.json()['detail']

    response = _transition(client, order_id, assigned_reviewer_headers, 'final_review')
    assert response.status_code == 200

    response = _transition(client, order_id, other_admin_headers, 'approved')
    assert response.status_code == 403
    assert 'assigned final approver' in response.json()['detail']

    response = _transition(client, order_id, assigned_admin_headers, 'approved')
    assert response.status_code == 200
    approved_order = response.json()['data']
    assert approved_order['status'] == 'approved'
    assert approved_order['final_approver_username'] == 'admin'


def test_change_order_template_snapshot_is_frozen(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')

    order = _create_order(
        client,
        requester_headers,
        command_template={
            'scenario_id': 'vlan-provision',
            'platform': 'cisco_ios',
            'variables': {
                'vlan_id': '200',
                'vlan_name': 'APP_USERS',
                'interfaces': 'GigabitEthernet0/0/1,GigabitEthernet0/0/2',
            },
        },
        commands=[],
        rollback_plan='',
    )

    assert order['command_template']['scenario_id'] == 'vlan-provision'
    assert order['command_template']['platform'] == 'cisco_ios'
    assert order['command_template']['preview']['execute'][0] == 'vlan 200'
    assert any('switchport access vlan 200' in command for command in order['commands'])
    assert order['rollback_plan'] == 'no vlan 200'


def test_invalid_transition_and_summary_endpoint(client: TestClient) -> None:
    requester_headers = _auth_headers('alice', 'Operator', 'u-1')

    order = _create_order(client, requester_headers)
    order_id = order['id']

    response = _transition(client, order_id, requester_headers, 'approved')
    assert response.status_code == 400
    assert 'Invalid transition' in response.json()['detail']

    summary_response = client.get('/api/change-orders/summary', headers=requester_headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()['data']
    assert summary['total'] == 1
    assert summary['by_status']['draft'] == 1

    list_response = client.get('/api/change-orders?search=核心交换机', headers=requester_headers)
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload['total'] == 1
    assert payload['data'][0]['order_number'].startswith('BG')