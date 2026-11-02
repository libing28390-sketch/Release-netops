from __future__ import annotations

import pytest

from database import get_db_connection
from services.asset_chassis_serial_service import sync_asset_chassis_members
from backend.tests.configuration.test_asset_chassis_members import _add_asset_device, _member, _snapshot


def _sync(conn, snapshot):
    return sync_asset_chassis_members(
        conn, "dynamic-asset", snapshot, device_id="dynamic-device", management_ip="192.0.2.71"
    )


def test_dynamic_stack_partial_then_complete_replaces_only_sn_members(isolated_db):
    with get_db_connection() as conn:
        _add_asset_device(conn, "dynamic-asset", "dynamic-device", "192.0.2.71", serial_number="OLD-AUTO", source="snmp_entity_fixed_get")
        conn.execute("UPDATE physical_assets SET model = 'OPERATOR-MODEL', hostname = 'OPERATOR-NAME' WHERE id = 'dynamic-asset'")
        indices = (4, 9001, 16777217, 16777218)
        snapshot = _snapshot("2026-11-02T00:00:00Z", [_member(i, f"STACK-{i}", name=f"Chassis {i}", model="MEMBER-MODEL") for i in indices])
        result = _sync(conn, snapshot)
        assert result["members_count"] == 4
        assert result["synced_serial_number"] == ""

        partial = _snapshot("2026-11-02T00:01:00Z", [_member(9001, "STACK-9001")], failed=(16777217,), status="partial")
        assert _sync(conn, partial)["members_count"] == 4
        complete = _snapshot("2026-11-02T00:02:00Z", [_member(9001, "STACK-9001")])
        outcome = _sync(conn, complete)
        assert outcome["status"] == "synced"
        assert outcome["members_count"] == 1
        assert outcome["synced_serial_number"] == "STACK-9001"
        member = conn.execute("SELECT entity_name, model FROM asset_chassis_members WHERE asset_id = 'dynamic-asset' AND entity_index = 9001").fetchone()
        assert tuple(member) == ("Chassis 9001", "MEMBER-MODEL")
        asset = conn.execute("SELECT model, hostname, vendor FROM physical_assets WHERE id = 'dynamic-asset'").fetchone()
        assert tuple(asset) == ("OPERATOR-MODEL", "OPERATOR-NAME", "H3C")
        assert _sync(conn, snapshot)["status"] == "superseded"
        conn.commit()


@pytest.mark.parametrize("case", ["duplicate", "placeholder", "candidate", "invalid-discovery"])
def test_duplicate_serials_sync_when_complete_but_uncertain_snapshots_preserve_prior_data(isolated_db, case):
    with get_db_connection() as conn:
        _add_asset_device(conn, "dynamic-asset", "dynamic-device", "192.0.2.71")
        _sync(conn, _snapshot("2026-11-02T00:00:00Z", [_member(9001, "KNOWN-SERIAL")]))
        current = _snapshot("2026-11-02T00:01:00Z", [_member(9002, "NEW-SERIAL")])
        if case == "duplicate":
            current = _snapshot("2026-11-02T00:01:00Z", [_member(9002, "SAME-SERIAL"), _member(9003, "same-serial")])
        elif case == "placeholder":
            current = _snapshot("2026-11-02T00:01:00Z", [_member(9002, "unknown")])
        elif case == "candidate":
            current["candidates"] = [{"entity_index": 9003, "serial_number": "MODULE-SERIAL"}]
            current["serial_complete"] = False
        else:
            current["discovered_indices"] = [None]
        result = _sync(conn, current)
        if case == "duplicate":
            assert result["status"] == "synced"
            assert result["synced_serial_number"] == "SAME-SERIAL"
            assert result["members_count"] == 2
            assert conn.execute("SELECT serial_number FROM physical_assets WHERE id = 'dynamic-asset'").fetchone()[0] == "SAME-SERIAL"
            assert [
                tuple(row)
                for row in conn.execute("SELECT entity_index, serial_number FROM asset_chassis_members WHERE asset_id = 'dynamic-asset' ORDER BY entity_index").fetchall()
            ] == [(9002, "SAME-SERIAL"), (9003, "same-serial")]
        else:
            assert result["status"] == "partial"
            assert result["synced_serial_number"] == "KNOWN-SERIAL"
            assert conn.execute("SELECT serial_number FROM asset_chassis_members WHERE asset_id = 'dynamic-asset' AND entity_index = 9001").fetchone()[0] == "KNOWN-SERIAL"
            if case == "placeholder":
                assert result["members_count"] == 1
        conn.commit()
