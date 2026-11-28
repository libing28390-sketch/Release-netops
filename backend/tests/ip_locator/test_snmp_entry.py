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
        'fdb_evidence': [{'device_id': 's5', 'interface': 'GigabitEthernet1/0/2', 'mac': '8e4757600706', 'vlan': '7', 'generation': 17}],
        'evidence_collected_at': '2026-11-03T09:00:00+00:00',
        'vrf_context_status': 'unknown',
        'collection_source': 'snmp',
    }
    monkeypatch.setattr(trace, '_load_devices', lambda **kw: [{'id': 's5', 'hostname': 'S6850-5'}, {'id': 'ac20', 'hostname': 'AC_20'}])
    monkeypatch.setattr(evidence, 'find_current_endpoint_evidence', lambda *a, **kw: deepcopy(proof))
    monkeypatch.setattr(trace, '_trace_contract_version', lambda: 'test-snmp')
    # This fixture supplies a synthetic projection, not real collection rows.
    # The generation lock itself is covered by test_collection_publication_fence.
    monkeypatch.setattr(tasks, '_lock_current_collection_generations', lambda *a, **kw: True)
    monkeypatch.setattr(trace, '_cache_for_scope', lambda *a: pytest.fail('must not read old CLI cache'))
    return proof

def test_snmp_evidence_precedes_core_route_queries(setup_snmp, monkeypatch):
    monkeypatch.setattr(trace.legacy, 'run_endpoint_fact_collector', lambda **kw: pytest.fail('fresh evidence must not refresh'))
    result = trace.add_legacy_compatibility(trace.trace_ip('172.16.5.10', authorized_device_ids=['s5', 'ac20']))
    assert result['found'] is True
    assert result['source'] == 'ipam_current'
    assert result['locations'][0]['type'] == 'PATH_TRACED'
    assert result['locations'][0]['port'] == 'GigabitEthernet1/0/2'
    assert result['queried_devices']['route'] == []
    assert result['l3_paths'] == []
    assert result['trace_status'] == 'terminal'
    assert result['mac_lookup']['status'] == 'found'

def test_force_refresh_bypasses_current_projection_without_writing_legacy_endpoint_history(setup_snmp, monkeypatch):
    calls = []
    monkeypatch.setattr(evidence, 'find_current_endpoint_evidence', lambda *a, **kw: calls.append('current') or deepcopy(setup_snmp))
    monkeypatch.setattr(trace.legacy, 'run_endpoint_fact_collector', lambda **kw: pytest.fail('locator must not invoke the legacy endpoint/history writer'))
    monkeypatch.setattr(trace, '_cache_for_scope', lambda *_a, **_kw: (None, ''))
    monkeypatch.setattr(trace, '_trace_ip_uncached', lambda *_a, **_kw: {'source': 'cli', 'found': True})
    result = trace.trace_ip('172.16.5.10', force_refresh=True, authorized_device_ids=['s5', 'ac20'])
    assert calls == []
    assert result == {'source': 'cli', 'found': True}

@pytest.mark.parametrize('changed', [False, True])
def test_snmp_manifest_rechecks_source_before_publication(setup_snmp, monkeypatch, changed):
    result = trace.trace_ip('172.16.5.10', authorized_device_ids=['s5'])
    current = deepcopy(setup_snmp)
    if changed:
        current['location']['port'] = 'GigabitEthernet1/0/3'
    monkeypatch.setattr(evidence, 'find_current_endpoint_evidence', lambda *a, **kw: current)
    class Conn:
        def execute(self, sql):
            assert sql in {"SAVEPOINT locator_current_fence", "RELEASE SAVEPOINT locator_current_fence"}
    valid, gaps = tasks._dependency_manifest_current_in_transaction(Conn(), result['dependency_manifest'], lock=True)
    assert valid is not changed
    assert gaps == (['dependency_changed:current_endpoint'] if changed else [])

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
    monkeypatch.setattr(evidence, 'find_current_endpoint_evidence', lambda *a, **kw: current)
    saved = tasks.save_locator_run_result(run['id'], result=result, status='completed')
    assert saved['status'] == ('partial' if changed else 'completed')
    assert saved['result']['source'] == 'ipam_current'
    assert saved['result']['dependency_fence']['status'] == ('changed' if changed else 'current')
    if changed:
        assert saved['result']['status'] == 'partial'
        assert saved['result']['found'] is False
        assert saved['result']['conclusion'] == 'dependency_changed'
        assert not saved['result'].get('location')
        assert saved['result']['locations'] == []
        assert saved['result']['terminal_candidates'] == []
    else:
        assert saved['result']['found'] is True
