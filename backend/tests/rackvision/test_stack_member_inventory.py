from __future__ import annotations

import pytest

from database import get_db_connection
from services.stack_member_service import (
    commit_stack_member_import,
    list_stack_members,
    preview_stack_member_import,
    reconcile_stack_members_with_snmp,
    replace_stack_member,
)


def _seed_logical_stack(asset_id: str, asset_tag: str, hostname: str, mgmt_ip: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO physical_assets
               (id, asset_tag, hostname, asset_type, management_ip, vendor, model, status, created_at, updated_at)
               VALUES (?, ?, ?, 'network_device', ?, 'H3C', 'S6850', 'active', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')""",
            (asset_id, asset_tag, hostname, mgmt_ip),
        )
        conn.commit()


def test_stack_member_idempotent_import_and_conflict_detection(isolated_db) -> None:
    _seed_logical_stack('asset-stack-01', 'WH-ACC-STACK01', 'WH-ACC-STACK01', '10.10.10.21')
    _seed_logical_stack('asset-stack-02', 'WH-ACC-STACK02', 'WH-ACC-STACK02', '10.10.10.22')

    rows = [
        {
            'row_number': 2,
            'stack_asset_tag': 'WH-ACC-STACK01',
            'member_number': 1,
            'physical_asset_tag': 'PHY-S6850-01A',
            'serial_number': 'SN-STACK-01A',
            'model': 'S6850-56HF',
            'rack_name': 'RACK-A01',
            'u_start': 40,
            'u_height': 1,
        },
        {
            'row_number': 3,
            'stack_asset_tag': 'WH-ACC-STACK01',
            'member_number': 2,
            'physical_asset_tag': 'PHY-S6850-01B',
            'serial_number': 'SN-STACK-01B',
            'model': 'S6850-56HF',
            'rack_name': 'RACK-A01',
            'u_start': 39,
            'u_height': 1,
        },
    ]

    preview = preview_stack_member_import(rows)
    assert preview['can_commit'] is True
    assert preview['summary'] == {'total': 2, 'create': 2, 'update': 0, 'existing': 0, 'conflict': 0}

    first = commit_stack_member_import(rows)
    assert first['created'] == 2
    assert first['updated'] == 0
    assert first['unchanged'] == 0

    # Re-importing the exact same two chassis is strictly idempotent
    second = commit_stack_member_import(rows)
    assert second['created'] == 0
    assert second['updated'] == 0
    assert second['unchanged'] == 2

    members = list_stack_members('asset-stack-01')
    assert len(members) == 2
    assert [m['member_number'] for m in members] == [1, 2]

    # Conflict checks: cross-stack duplicate SN, missing stack, rack U overlap
    conflict_preview = preview_stack_member_import([
        {
            'row_number': 10,
            'stack_asset_tag': 'WH-ACC-STACK02',
            'member_number': 1,
            'physical_asset_tag': 'PHY-S6850-02A',
            'serial_number': 'SN-STACK-01A',  # already active on STACK01!
            'rack_name': 'RACK-B01',
            'u_start': 20,
            'u_height': 1,
        },
        {
            'row_number': 11,
            'stack_asset_tag': 'NO-SUCH-STACK',
            'member_number': 1,
            'serial_number': 'SN-NEW-999',
        },
    ])
    assert conflict_preview['can_commit'] is False
    fields = {(c['row_number'], c['field']) for c in conflict_preview['conflicts']}
    assert (10, 'serial_number') in fields
    assert (11, 'stack_asset_tag') in fields
    with pytest.raises(ValueError, match='conflict'):
        commit_stack_member_import([
            {
                'row_number': 10,
                'stack_asset_tag': 'WH-ACC-STACK02',
                'member_number': 1,
                'serial_number': 'SN-STACK-01A',
            }
        ])


def test_stack_member_snmp_reconciliation_and_replacement_preserves_operator_data(isolated_db) -> None:
    _seed_logical_stack('asset-stack-03', 'WH-ACC-STACK03', 'WH-ACC-STACK03', '10.10.10.23')
    commit_stack_member_import([
        {
            'stack_asset_tag': 'WH-ACC-STACK03',
            'member_number': 1,
            'physical_asset_tag': 'PHY-03-M1',
            'serial_number': 'SN-03-M1',
            'model': 'S6850',
            'rack_name': 'RACK-C01',
            'u_start': 30,
            'u_height': 1,
        },
        {
            'stack_asset_tag': 'WH-ACC-STACK03',
            'member_number': 2,
            'physical_asset_tag': 'PHY-03-M2',
            'serial_number': 'SN-03-M2',
            'model': 'S6850',
            'rack_name': 'RACK-C01',
            'u_start': 29,
            'u_height': 1,
        },
    ])

    # Partial SNMP read returns member 1 (at entity_index 2 after master switchover!) + unregistered chassis 3
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO asset_chassis_members
               (asset_id, entity_index, serial_number, entity_name, entity_description, model, collected_at)
               VALUES
                 ('asset-stack-03', 2, 'SN-03-M1', 'Chassis 2', 'H3C S6850', 'S6850', '2026-11-19T12:00:00Z'),
                 ('asset-stack-03', 3, 'SN-03-EXTRA', 'Chassis 3', 'H3C S6850', 'S6850', '2026-11-19T12:00:00Z')""",
        )
        conn.commit()

    recon = reconcile_stack_members_with_snmp('asset-stack-03')
    assert len(recon['matched_members']) == 1
    assert recon['matched_members'][0]['serial_number'] == 'SN-03-M1'
    assert recon['matched_members'][0]['entity_index'] == 2
    assert len(recon['missing_members']) == 1
    assert recon['missing_members'][0]['serial_number'] == 'SN-03-M2'
    assert len(recon['unregistered_chassis']) == 1
    assert recon['unregistered_chassis'][0]['serial_number'] == 'SN-03-EXTRA'

    # Operator asset tag and rack coordinates remain intact even for missing member
    members_after = list_stack_members('asset-stack-03')
    m2 = next(m for m in members_after if m['member_number'] == 2)
    assert m2['physical_asset_tag'] == 'PHY-03-M2'
    assert m2['rack_name'] == 'RACK-C01'
    assert m2['u_start'] == 29
    assert m2['reconciliation_status'] == 'missing_in_snmp'

    # Replace member 2 chassis: retires old, inherits confirmed rack position on new active record
    replaced = replace_stack_member(
        m2['id'],
        new_serial_number='SN-03-M2-NEW',
        new_physical_asset_tag='PHY-03-M2-NEW',
        notes='RMA replacement',
    )
    assert replaced['retired_member']['status'] == 'replaced'
    assert replaced['retired_member']['replaced_by_id'] == replaced['new_member']['id']
    assert replaced['new_member']['status'] == 'active'
    assert replaced['new_member']['member_number'] == 2
    assert replaced['new_member']['serial_number'] == 'SN-03-M2-NEW'
    assert replaced['new_member']['rack_name'] == 'RACK-C01'
    assert replaced['new_member']['u_start'] == 29

    history = list_stack_members('asset-stack-03', include_history=True)
    assert len(history) == 3
    active_only = list_stack_members('asset-stack-03', include_history=False)
    assert len(active_only) == 2
