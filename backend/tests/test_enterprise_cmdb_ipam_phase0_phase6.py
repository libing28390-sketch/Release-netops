import json

import pytest

from core.rbac import authorize_resource
from database import get_db_connection
from database.migrations import get_applied_versions
from services import audit_service, cmdb_service, ipam_service, job_service, reconciliation_service
from services.discovery_service import resolve_discovery_profile


def test_enterprise_migration_and_fresh_schema(isolated_db):
    conn = get_db_connection()
    try:
        assert 8 in get_applied_versions(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for name in (
            'discovery_runs', 'discovery_observations', 'reconciliation_runs',
            'reconciliation_findings', 'reconciliation_actions', 'job_steps',
            'job_targets', 'job_artifacts', 'job_events', 'user_resource_scopes',
        ):
            assert name in tables
        audit_columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
        assert {'request_id', 'before_json', 'after_json'} <= audit_columns
        address_columns = {row[1] for row in conn.execute("PRAGMA table_info(ip_addresses)").fetchall()}
        assert {'available_after', 'released_at', 'purpose', 'tenant_id', 'site_id'} <= address_columns
    finally:
        conn.close()


def test_audit_standard_redacts_sensitive_values(isolated_db):
    event_id = audit_service.log_audit_event(
        event_type='ipam.address.test', category='ipam', severity='info', status='success',
        summary='test', actor_username='tester', target_type='ip_address',
        request_id='req-123', before={'password': 'secret', 'hostname': 'old'},
        after={'token': 'abc', 'hostname': 'new'}, details={'snmp_community': 'public'},
    )
    item = audit_service.get_audit_event(event_id)
    assert item['request_id'] == 'req-123'
    assert item['before']['password'] == '[REDACTED]'
    assert item['after']['token'] == '[REDACTED]'
    assert item['details']['snmp_community'] == '[REDACTED]'
    assert 'secret' not in json.dumps(item)


def test_cmdb_tenant_scoped_vrf_and_vlan_uniqueness(isolated_db):
    conn = get_db_connection()
    try:
        t1 = cmdb_service.create_tenant(conn, name='Tenant A')
        t2 = cmdb_service.create_tenant(conn, name='Tenant B')
        cmdb_service.create_vrf(conn, vrf_name='PROD', tenant_id=t1['id'])
        cmdb_service.create_vrf(conn, vrf_name='PROD', tenant_id=t2['id'])
        with pytest.raises(ValueError, match='already exists'):
            cmdb_service.create_vrf(conn, vrf_name='PROD', tenant_id=t1['id'])
        site = cmdb_service.create_site(conn, site_code='SHA-DC1', site_name='Shanghai DC', tenant_id=t1['id'])
        cmdb_service.create_vlan(conn, vlan_id=100, name='SERVER', site_id=site['id'], tenant_id=t1['id'])
        with pytest.raises(ValueError, match='already exists'):
            cmdb_service.create_vlan(conn, vlan_id=100, name='DUP', site_id=site['id'], tenant_id=t1['id'])
    finally:
        conn.close()


def test_ipam_lifecycle_quarantine_and_conflict_domains(isolated_db):
    prefix = ipam_service.create_subnet(prefix='198.51.100.0/29', tenant_id='tenant-default')
    first = ipam_service.allocate_next_address(prefix['id'], hostname='app-1', requested_by='tester', purpose='app')
    assert first['status'] == 'allocated'
    assert ipam_service.release_address(first['id'], released_by='tester')
    conn = get_db_connection()
    try:
        released = conn.execute("SELECT status, released_at, available_after FROM ip_addresses WHERE id = ?", (first['id'],)).fetchone()
        assert released['status'] == 'released'
        assert released['released_at']
        assert released['available_after'] > released['released_at']
    finally:
        conn.close()
    second = ipam_service.allocate_next_address(prefix['id'], hostname='app-2', requested_by='tester')
    assert second['address'] != first['address']
    with pytest.raises(ValueError, match='allocated IP'):
        ipam_service.create_vip(address=second['address'], vip_type='vrrp', tenant_id='tenant-default')
    with pytest.raises(ValueError, match='allocated IP'):
        ipam_service.create_lease(address=second['address'], mac_address='00:11:22:33:44:55')


def test_reconciliation_approval_is_the_authoritative_write_boundary(isolated_db):
    prefix = ipam_service.create_subnet(prefix='203.0.113.0/29', tenant_id='tenant-default')
    run = reconciliation_service.create_reconciliation_run(
        discovery_run_id=None, requested_by='collector', findings=[{
            'finding_type': 'undocumented_endpoint', 'risk_level': 'medium',
            'target_type': 'ip_address', 'target_id': '203.0.113.2',
            'observed': {'address': '203.0.113.2'},
            'proposed': {'subnet_id': prefix['id'], 'address': '203.0.113.2', 'hostname': 'edge-host'},
        }],
    )
    finding = reconciliation_service.list_findings(run_id=run['id'])[0]
    conn = get_db_connection()
    try:
        assert conn.execute("SELECT 1 FROM ip_addresses WHERE address = '203.0.113.2'").fetchone() is None
    finally:
        conn.close()
    action = reconciliation_service.request_action(
        finding['id'], action_type='register_ip', requested_by='operator',
    )
    reconciliation_service.approve_action(action['id'], approved_by='admin')
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT status, source_type FROM ip_addresses WHERE address = '203.0.113.2'").fetchone()
        assert row['status'] == 'allocated'
        assert row['source_type'] == 'discovered'
    finally:
        conn.close()


def test_unified_job_lifecycle_and_device_lock(isolated_db):
    job = job_service.create_job(
        job_type='discovery', task_name='Discover', created_by='operator',
        targets=[{'target_id': 'device-a'}, {'target_id': 'device-b'}],
        steps=['connect', 'collect'], concurrency_limit=1, retry_limit=1,
    )
    claimed = job_service.claim_targets(job['id'])
    assert len(claimed) == 1
    assert job_service.claim_targets(job['id']) == []
    updated = job_service.complete_target(claimed[0]['id'], status='succeeded', result={'ok': True})
    assert updated['progress'] == 50
    second = job_service.claim_targets(job['id'])
    assert len(second) == 1
    finished = job_service.complete_target(second[0]['id'], status='failed', error_message='timeout')
    assert finished['status'] == 'partially_failed'
    assert finished['success_count'] == 1
    assert finished['failed_count'] == 1


def test_resource_scope_and_multi_vendor_discovery_profiles(isolated_db):
    assert authorize_resource({'role': 'Viewer'}, 'ip_address', 'read')
    assert not authorize_resource({'role': 'Viewer'}, 'ip_address', 'update')
    assert not authorize_resource(
        {'role': 'Operator', 'tenant_id': 'tenant-a'}, 'ip_address', 'update', tenant_id='tenant-b',
    )
    assert resolve_discovery_profile('huawei_vrpv8')[1]['version'].startswith('display')
    assert resolve_discovery_profile('hp_comware')[1]['brief'].startswith('display')
    assert resolve_discovery_profile('cisco_ios')[1]['brief'].startswith('show')
    with pytest.raises(ValueError, match='Refusing Cisco command fallback'):
        resolve_discovery_profile('unknown_vendor')
