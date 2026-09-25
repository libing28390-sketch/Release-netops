import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import services.snmp_service
from backend.api.devices import clean_system_hostname, batch_sync_hostname, BatchSyncHostnamePayload
from services.hostname_sync_service import sync_device_hostname_metadata


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


@pytest.mark.anyio
async def test_batch_sync_hostname_mocked():
    fake_devices = [
        {"id": "dev-1", "hostname": "temp-01", "ip_address": "192.168.1.1", "asset_id": "ast-1"},
        {"id": "dev-2", "hostname": "core-sw-02", "ip_address": "192.168.1.2", "asset_id": "ast-2"},
    ]

    def fake_sync_hostname_metadata(_conn, device_id, raw_sys_name):
        device = next(device for device in fake_devices if device["id"] == device_id)
        return {
            "device_id": device_id,
            "previous_hostname": device["hostname"],
            "hostname": clean_system_hostname(raw_sys_name),
        }

    with patch("backend.api.devices.get_db_connection") as mock_conn_fn, \
         patch("backend.api.devices.resolve_collector_credentials") as mock_creds, \
         patch.object(services.snmp_service, "_snmp_get", new_callable=AsyncMock) as mock_snmp, \
         patch(
             "services.hostname_sync_service.sync_device_hostname_metadata",
             side_effect=fake_sync_hostname_metadata,
         ) as mock_sync_hostname:
        
        mock_conn = mock_conn_fn.return_value
        mock_conn.execute.return_value.fetchall.return_value = fake_devices
        mock_creds.return_value = {"snmp": {"server": "192.168.1.1", "community": "public", "port": 161}}
        mock_snmp.side_effect = ["core-sw-01.CCIE", "core-sw-02.CCIE"]
        
        payload = BatchSyncHostnamePayload(device_ids=["dev-1", "dev-2"])
        result = await batch_sync_hostname(payload)
        
        assert result["success"] is True
        assert result["total"] == 2
        assert result["updated"] == 1
        assert result["unchanged"] == 1
        assert result["failed"] == 0
        assert len(result["details"]) == 2
        assert result["details"][0]["status"] == "updated"
        assert result["details"][0]["new_hostname"] == "core-sw-01"
        assert result["details"][1]["status"] == "unchanged"
        assert result["details"][1]["new_hostname"] == "core-sw-02"
        assert mock_sync_hostname.call_count == 2
