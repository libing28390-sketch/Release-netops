"""SNMP entry-point contracts; device traffic is mocked."""
from copy import deepcopy
import pytest
from services import ip_locator_trace_service as trace
from services import ip_locator_endpoint_evidence as evidence
from services import ip_locator_task_service as tasks

@pytest.fixture
def setup_snmp(monkeypatch):
    proof = {
        'location': {'device_id': 's5', 'device': 'S6850-5', 'port': 'GigabitEthernet1/0/2', 'mac': '8e4757600706', 'vlan': '7'},
        'arp_evidence': [{'device_id': 's5', 'device': 'S6850-5', 'interface': 'GE1/0/2', 'mac': '8e4757600706', 'vlan': '7'}],
        'evidence_collected_at': '2026-11-03T09:00:00+00:00',
        'vrf_context_status': 'unknown',
    }
    monkeypatch.setattr(trace, '_load_devices', lambda **kw: [{'id': 's5', 'hostname': 'S6850-5'}, {'id': 'ac20', 'hostname': 'AC_20'}])
    monkeypatch.setattr(evidence, 'find_endpoint_evidence', lambda *a, **kw: deepcopy(proof))
    monkeypatch.setattr(evidence, 'endpoint_source_device_ids', lambda *a, **kw: ['s5'])
    monkeypatch.setattr(trace, '_trace_contract_version', lambda: 'test-snmp')
    monkeypatch.setattr(trace, '_cache_for_scope', lambda *a: pytest.fail('must not read old CLI cache'))
    return proof

def test_snmp_evidence_precedes_core_route_queries(setup_snmp, monkeypatch):
    monkeypatch.setattr(trace.legacy, 'run_endpoint_fact_collector', lambda **kw: pytest.fail('fresh evidence must not refresh'))
    result = trace.add_legacy_compatibility(trace.trace_ip('172.16.5.10', authorized_device_ids=['s5', 'ac20']))
    assert result['found'] is True
    assert result['source'] == 'snmp'
    assert result['locations'][0]['type'] == 'SNMP_ENDPOINT'
    assert result['locations'][0]['port'] == 'GigabitEthernet1/0/2'
    assert result['queried_devices']['route'] == []
    assert result['l3_paths'] == []
    assert result['trace_status'] == 'terminal'
    assert result['mac_lookup']['status'] == 'found'

def test_realtime_snmp_refresh_only_known_authorized_source(setup_snmp, monkeypatch):
    calls = []
    monkeypatch.setattr(trace.legacy, 'run_endpoint_fact_collector', lambda **kw: calls.append(kw))
    result = trace.trace_ip('172.16.5.10', force_refresh=True, authorized_device_ids=['s5', 'ac20'])
    assert calls == [{'device_ids': {'s5'}}]
    assert result['refreshed_device_ids'] == ['s5']
    assert result['queried_devices']['arp'] == ['S6850-5']
    assert result['queried_devices']['route'] == []

@pytest.mark.parametrize('changed', [False, True])
def test_snmp_manifest_rechecks_source_before_publication(setup_snmp, monkeypatch, changed):
    result = trace.trace_ip('172.16.5.10', authorized_device_ids=['s5'])
    current = deepcopy(setup_snmp)
    if changed:
        current['location']['port'] = 'GigabitEthernet1/0/3'
    monkeypatch.setattr(evidence, 'find_endpoint_evidence', lambda *a, **kw: current)
    valid, gaps = tasks._dependency_manifest_current_in_transaction(object(), result['dependency_manifest'], lock=True)
    assert valid is not changed
    assert gaps == (['dependency_changed:snmp_endpoint'] if changed else [])

def test_missing_snmp_evidence_keeps_cli_fallback(monkeypatch):
    monkeypatch.setattr(trace, '_try_snmp_endpoint', lambda *a, **kw: None)
    monkeypatch.setattr(trace, '_cache_for_scope', lambda *a: (None, ''))
    monkeypatch.setattr(trace, '_trace_ip_uncached', lambda *a, **kw: {'source': 'cli', 'found': False})
    assert trace.trace_ip('172.16.5.10')['source'] == 'cli'

@pytest.mark.parametrize('changed', [False, True])
def test_snmp_result_publication_uses_postgresql_fence(isolated_db, setup_snmp, monkeypatch, changed):
    result = trace.trace_ip('172.16.5.10', authorized_device_ids=['s5'])
    run = tasks.create_locator_run(owner_id='snmp-proof-test', target_ip='172.16.5.10')
    current = deepcopy(setup_snmp)
    if changed:
        current['location']['port'] = 'GigabitEthernet1/0/3'
    monkeypatch.setattr(evidence, 'find_endpoint_evidence', lambda *a, **kw: current)
    saved = tasks.save_locator_run_result(run['id'], result=result, status='completed')
    assert saved['status'] == ('partial' if changed else 'completed')
    assert saved['result']['source'] == 'snmp'
    assert saved['result']['dependency_fence']['status'] == ('changed' if changed else 'current')
