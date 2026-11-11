import asyncio

import pytest

from database import get_db_connection
from services import snmp_service as snmp


def vlan_tables():
    return {
        snmp.DOT1Q_VLAN_CURRENT_EGRESS_PORTS: [('0.7', b'\x20')],
        snmp.DOT1Q_VLAN_CURRENT_UNTAGGED_PORTS: [('0.7', b'\x20')],
        snmp.DOT1Q_PORT_PVID: [('3', 7)],
        snmp.DOT1D_BASE_PORT_IF_INDEX: [('3', 3), ('50', 50)],
        snmp.DOT1Q_VLAN_STATIC_NAME: [('7', b'User')],
    }


def test_extra_bridge_port_without_pvid_keeps_proven_access_port(monkeypatch):
    tables = vlan_tables()
    async def walk(_ip, _credentials, oid, *_a, **_kw):
        return tables[oid]
    monkeypatch.setattr(snmp, '_snmp_bulk_walk_complete', walk)
    result = asyncio.run(snmp.collect_qbridge_interface_vlan_data(
        '192.0.2.1', 'fixture', {3: 'GigabitEthernet1/0/2', 50: 'Ten-GigabitEthernet1/0/49'},
    ))
    assert result['interfaces'] == [{
        'bridge_port': 3, 'if_index': 3, 'interface': 'GigabitEthernet1/0/2',
        'pvid': 7, 'tagged_vlans': [], 'untagged_vlans': [7],
    }]


def test_pvid_without_bridge_mapping_still_rejects_snapshot(monkeypatch):
    tables = vlan_tables()
    tables[snmp.DOT1Q_PORT_PVID].append(('99', 7))
    async def walk(_ip, _credentials, oid, *_a, **_kw):
        return tables[oid]
    monkeypatch.setattr(snmp, '_snmp_bulk_walk_complete', walk)
    with pytest.raises(RuntimeError, match='unmapped bridge port'):
        asyncio.run(snmp.collect_qbridge_interface_vlan_data(
            '192.0.2.1', 'fixture', {3: 'GE1/0/2', 50: 'XGE1/0/49'},
        ))


@pytest.mark.parametrize('attribute_failure', [False, True])
def test_fdb_success_survives_independent_port_attribute_failure(isolated_db, monkeypatch, attribute_failure):
    from services import ip_locator_service as locator
    from services import vault_service
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id)
               VALUES ('fixture', 'fixture', '192.0.2.1', 'cisco_ios', 'online', 'tenant-default')"""
        )
        conn.commit()
    monkeypatch.setattr(locator, 'is_snmp_collection_enabled', lambda _d: True)
    monkeypatch.setattr(vault_service, 'resolve_collector_credentials', lambda _d: {
        'snmp': {'configured': True, 'community': 'fixture', 'version': '2c'},
    })
    async def fdb(*_a, **_kw):
        return [{'mac': '001122334455', 'vlan': '7', 'port': 'GigabitEthernet1/0/2'}]
    async def attributes(*_a, **_kw):
        if attribute_failure:
            raise RuntimeError('fixture attributes unavailable')
        return {'interfaces': [{'interface': 'GigabitEthernet1/0/2', 'pvid': 7}], 'vlans': [{'vlan_id': 7}]}
    monkeypatch.setattr(snmp, 'collect_bridge_mac_table', fdb)
    monkeypatch.setattr(snmp, 'collect_qbridge_interface_vlan_data', attributes)
    result = locator._collect_full_mac_table_from_device({'id': 'fixture', 'ip_address': '192.0.2.1'}, snmp_only=True)
    assert result['success']
    assert result['transport'] == 'snmp'
    assert len(result['records']) == 1
    if attribute_failure:
        assert result['interface_evidence_error'] == 'fixture attributes unavailable'
    else:
        assert result['interface_vlan_data']['interfaces'][0]['pvid'] == 7
