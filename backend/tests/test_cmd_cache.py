import pytest
import time
from unittest.mock import MagicMock, patch

from core.cmd_cache import (
    get_cached_command,
    set_cached_command,
    get_suggested_ttl,
    clear_cmd_cache
)
from services.ip_locator_service import _send_command

@pytest.fixture(autouse=True)
def clean_cache():
    clear_cmd_cache()
    yield
    clear_cmd_cache()

def test_suggested_ttl():
    # Performance metric command should have short TTL (15s)
    assert get_suggested_ttl("show processes cpu") == 15
    assert get_suggested_ttl("display memory-usage") == 15
    assert get_suggested_ttl("show standby brief") == 15

    # Routing, ARP, LLDP, etc., should have long TTL (300s)
    assert get_suggested_ttl("show ip route vrf global 1.1.1.1") == 300
    assert get_suggested_ttl("display arp vpn-instance vrf1 | include 2.2.2.2") == 300
    assert get_suggested_ttl("show lldp neighbors") == 300
    assert get_suggested_ttl("show mac address-table") == 300

    # Default TTL
    assert get_suggested_ttl("show clock") == 60

def test_command_caching_and_expiration():
    device_ip = "192.168.1.1"
    command = "show ip route 8.8.8.8"
    output = "Routing entry for 8.8.8.8/32\n  Known via static"

    # Initially not in cache
    assert get_cached_command(device_ip, command) is None

    # Use patch to mock the system time passage deterministically
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        
        # Set cache with 1s TTL (expires at 1001.0)
        set_cached_command(device_ip, command, output, ttl=1)
        
        # 0.5s later: should still be in cache
        mock_time.return_value = 1000.5
        assert get_cached_command(device_ip, command) == output

        # 1.5s later: should have expired
        mock_time.return_value = 1001.5
        assert get_cached_command(device_ip, command) is None

@patch("services.ip_locator_service.ConnectHandler")
def test_send_command_caching_integration(mock_connect):
    # Setup mock netmiko client
    mock_client = MagicMock()
    mock_client.send_command.return_value = "Mocked Route Output"
    mock_connect.return_value.__enter__.return_value = mock_client

    device_info = {
        "id": "dev-123",
        "hostname": "test-router",
        "ip_address": "192.168.100.1",
        "platform": "cisco_ios",
        "username": "admin",
        "password": "pwd"
    }
    command = "show ip route 10.0.0.1"

    # First call: cache miss, should call netmiko ConnectHandler
    res1 = _send_command(device_info, command)
    assert res1 == "Mocked Route Output"
    assert mock_connect.call_count == 1
    assert mock_client.send_command.call_count == 1

    # Second call: cache hit, should NOT call netmiko ConnectHandler again
    res2 = _send_command(device_info, command)
    assert res2 == "Mocked Route Output"
    assert mock_connect.call_count == 1  # Still 1
    assert mock_client.send_command.call_count == 1  # Still 1
