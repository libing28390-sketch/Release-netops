from unittest.mock import MagicMock

from services.hostname_sync_service import clean_system_hostname, sync_device_hostname_metadata


def test_clean_system_hostname():
    # Domain suffix removal
    assert clean_system_hostname("core-sw-01.CCIE") == "core-sw-01"
    assert clean_system_hostname("switch-agg-02.corp.local") == "switch-agg-02"
    assert clean_system_hostname("leaf-101.dc1") == "leaf-101"
    
    # Simple hostnames without dots
    assert clean_system_hostname("core-sw-01") == "core-sw-01"
    assert clean_system_hostname("H3C-S6800") == "H3C-S6800"
    
    # Strip carriage return/newlines
    assert clean_system_hostname("sw-access-01\r\n") == "sw-access-01"
    assert clean_system_hostname("  router-border-01.internal  ") == "router-border-01"
    
    # Empty or None handling
    assert clean_system_hostname("") == ""
    assert clean_system_hostname(None) == ""


def test_sync_hostname_metadata_projects_to_linked_asset_and_topology():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "id": "dev-1",
        "hostname": "old-name",
        "asset_id": "asset-1",
    }

    result = sync_device_hostname_metadata(conn, "dev-1", "core-sw-01.corp.local\n")

    assert result == {
        "device_id": "dev-1",
        "asset_id": "asset-1",
        "previous_hostname": "old-name",
        "hostname": "core-sw-01",
        "raw_sys_name": "core-sw-01.corp.local\n",
    }
    sql_calls = [call.args[0] for call in conn.execute.call_args_list]
    assert any("UPDATE devices SET hostname" in sql for sql in sql_calls)
    assert any("UPDATE physical_assets SET hostname" in sql for sql in sql_calls)
    assert any("UPDATE topology_observations SET source_hostname" in sql for sql in sql_calls)
