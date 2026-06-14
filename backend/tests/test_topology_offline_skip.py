import pytest
from database import get_db_connection
from services.topology_service import discover_device_neighbors

@pytest.mark.anyio
async def test_discover_device_neighbors_skips_offline(isolated_db):
    conn = get_db_connection()
    try:
        # Clear devices
        conn.execute("DELETE FROM devices")
        # Insert a device that is offline
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, status, username, password)
            VALUES ('dev-offline-1', 'switch-offline', '10.0.0.99', 'offline', 'admin', 'password')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Call discover_device_neighbors, it should raise RuntimeError('device_is_offline')
    with pytest.raises(RuntimeError) as excinfo:
        await discover_device_neighbors('dev-offline-1')
    
    assert str(excinfo.value) == 'device_is_offline'


@pytest.mark.anyio
async def test_discover_device_neighbors_proceeds_online(isolated_db, monkeypatch):
    conn = get_db_connection()
    try:
        # Clear devices
        conn.execute("DELETE FROM devices")
        # Insert a device that is online
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, status, username, password)
            VALUES ('dev-online-1', 'switch-online', '10.0.0.100', 'online', 'admin', 'password')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Mock _collect_device_observations to avoid network attempts
    async def mock_collect_device_observations(device):
        return [], 'mock'

    import services.topology_service
    monkeypatch.setattr(services.topology_service, "_collect_device_observations", mock_collect_device_observations)

    # Calling discover_device_neighbors should proceed and not raise device_is_offline
    res = await discover_device_neighbors('dev-online-1')
    assert res['device_id'] == 'dev-online-1'
    assert res['discovery_method'] == 'mock'
