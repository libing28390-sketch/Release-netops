from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from api import assets
from database import get_db_connection
from services import snmp_import_identification_service as identity_service


def _create(actor, *, tag='SN-INTEGRATION', vendor='H3C', serial=''):
    return assets.create_asset(
        assets.AssetCreate(
            asset_type='network_device', asset_tag=tag, hostname=tag.lower(),
            management_ip='192.0.2.211', vendor=vendor,
            platform={'H3C': 'h3c_comware', 'Huawei': 'huawei_vrp', 'Cisco': 'cisco_ios'}[vendor],
            serial_number=serial,
        ),
        background_tasks=BackgroundTasks(), _user=actor,
    )


def _mock_identity(monkeypatch, *, vendor='H3C'):
    core = AsyncMock(return_value={
        'status': 'identified', 'detected_vendor': vendor, 'hostname_sync': {'status': 'synced', 'hostname': 'switch'},
        'detected_model': 'S6850', 'synced_model': 'S6850', 'model_source': 'entity_mib',
        'message': 'fixture identity',
    })
    monkeypatch.setattr(identity_service, '_identify_imported_device_core', core)
    monkeypatch.setattr(identity_service, '_resolve_probe_settings', lambda *_: ({'version': '2c', 'community': 'fixture-only'}, ''))
    return core


def _snapshot(*indices):
    return {
        'status': 'success', 'observed_at': datetime.now(timezone.utc).isoformat(),
        'members': [{
            'entity_index': index, 'serial_number': f'CHASSIS-SN-{index}',
            'entity_name': f'Chassis {index + 4}', 'entity_description': f'physical chassis {index}', 'model': 'S6850',
        } for index in indices],
        'absent_indices': [index for index in (1, 2, 3) if index not in indices],
        'failed_indices': [], 'discovered_indices': list(indices),
        'discovery_complete': True, 'serial_complete': True,
    }


def test_stack_sync_exposes_distinct_sn_records_and_preserves_manual_serial(isolated_db, make_user, monkeypatch):
    from services import asset_chassis_serial_service as chassis

    actor = make_user('sn-stack-admin', role='Administrator', tenant_id='tenant-default')
    asset = _create(actor, serial='OPERATOR-SN')
    _mock_identity(monkeypatch)
    read = AsyncMock(return_value=_snapshot(2, 3))
    monkeypatch.setattr(chassis, 'read_chassis_serials', read)
    monkeypatch.setattr(assets, '_sync_enriched_asset_rack_device', lambda *_: {'status': 'skipped'})

    outcome = assets.batch_snmp_sync_assets(assets.BatchAssetSnmpSyncRequest(asset_ids=[asset['id']]), _user=actor)
    assert outcome['results'][0]['serial_sync']['members_count'] == 2
    detail = assets.get_asset(asset['id'], _user=actor)
    listed = assets.list_assets(q='SN-INTEGRATION', page=1, page_size=10, _user=actor)['items'][0]
    assert detail['serial_number'] == listed['serial_number'] == 'OPERATOR-SN'
    for item in (detail, listed):
        members = item['chassis_members']
        assert [(member['entity_index'], member['serial_number']) for member in members] == [(2, 'CHASSIS-SN-2'), (3, 'CHASSIS-SN-3')]
        assert [member['entity_name'] for member in members] == ['Chassis 6', 'Chassis 7']
        assert 'fixture-only' not in str(members)
    read.assert_awaited_once()

    monkeypatch.setattr(assets, '_enforce_asset_row_scope', lambda *_args: (_ for _ in ()).throw(HTTPException(403, 'denied')))
    with pytest.raises(HTTPException) as denied:
        assets.get_asset(asset['id'], _user=actor)
    assert denied.value.status_code == 403


def test_single_chassis_fills_blank_asset_serial_after_identity(isolated_db, make_user, monkeypatch):
    from services import asset_chassis_serial_service as chassis

    actor = make_user('sn-single-admin', role='Administrator', tenant_id='tenant-default')
    asset = _create(actor)
    core = _mock_identity(monkeypatch)
    read = AsyncMock(return_value=_snapshot(1))
    monkeypatch.setattr(chassis, 'read_chassis_serials', read)
    with get_db_connection() as conn:
        device_id = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset['id'],)).fetchone()['id']
    result = asyncio.run(identity_service.identify_imported_device({'device_id': device_id}, asyncio.Semaphore(1)))
    core.assert_awaited_once()
    assert result['serial_sync']['status'] == 'synced'
    detail = assets.get_asset(asset['id'], _user=actor)
    assert detail['serial_number'] == 'CHASSIS-SN-1'
    assert detail['serial_number_source'] == 'snmp_entity_discovery'


@pytest.mark.parametrize('vendor', ['Cisco', 'Huawei'])
def test_other_vendors_use_standard_chassis_sn_after_identity(isolated_db, make_user, monkeypatch, vendor):
    from services import asset_chassis_serial_service as chassis

    actor = make_user('sn-other-vendor', role='Administrator', tenant_id='tenant-default')
    asset = _create(actor, vendor=vendor)
    core = _mock_identity(monkeypatch, vendor=vendor)
    read = AsyncMock(return_value=_snapshot(9001))
    monkeypatch.setattr(chassis, 'read_chassis_serials', read)
    with get_db_connection() as conn:
        device_id = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset['id'],)).fetchone()['id']
    result = asyncio.run(identity_service.identify_imported_device({'device_id': device_id}, asyncio.Semaphore(1)))
    assert result['serial_sync']['status'] == 'synced'
    read.assert_awaited_once_with('192.0.2.211', {'version': '2c', 'community': 'fixture-only'}, vendor=vendor)
    detail = assets.get_asset(asset['id'], _user=actor)
    assert detail['serial_number'] == 'CHASSIS-SN-9001'
    core.assert_awaited_once()


@pytest.mark.parametrize('vendor', ['Cisco', 'Huawei'])
def test_duplicate_import_queues_only_serial_refresh_for_other_vendors(isolated_db, make_user, vendor):
    from core.crypto import encrypt_credential

    actor = make_user('sn-duplicate-admin', role='Administrator', tenant_id='tenant-default')
    asset = _create(actor, vendor=vendor)
    with get_db_connection() as conn:
        conn.execute("UPDATE physical_assets SET snmp_community = ?, model = 'KEEP-MODEL' WHERE id = ?",
                     (encrypt_credential('fixture-community'), asset['id']))
        before = tuple(conn.execute("SELECT hostname, model, vendor, platform FROM physical_assets WHERE id = ?", (asset['id'],)).fetchone())
        conn.commit()
    background = BackgroundTasks()
    result = assets.import_assets([
        assets.AssetCreate(asset_type='network_device', asset_tag='SN-INTEGRATION',
                           management_ip='192.0.2.211', vendor=vendor, hostname='DO-NOT-RENAME')
    ], detailed=True, background_tasks=background, _user=actor)
    assert result['created'] == 0
    assert result['skipped'] == 1
    assert result['results'][0]['snmp_identification']['serial_sync']['status'] == 'pending'
    with get_db_connection() as conn:
        after = tuple(conn.execute("SELECT hostname, model, vendor, platform FROM physical_assets WHERE id = ?", (asset['id'],)).fetchone())
    assert after == before
