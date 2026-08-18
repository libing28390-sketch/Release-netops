import pytest
from pydantic import ValidationError
from api.assets import AssetCreate, AssetUpdate


def test_asset_create_valid_ipv4_and_ipv6():
    # Valid IPv4
    a1 = AssetCreate(asset_type='network_device', hostname='sw-1', management_ip='192.168.2.201', business_ip='10.0.0.1')
    assert a1.management_ip == '192.168.2.201'
    assert a1.business_ip == '10.0.0.1'

    # Valid IPv6
    a2 = AssetCreate(asset_type='server', hostname='srv-1', management_ip='2001:db8::1', business_ip='')
    assert a2.management_ip == '2001:db8::1'

    # Empty IP (allowed if optional)
    a3 = AssetCreate(asset_type='server', hostname='srv-2', management_ip='', business_ip='')
    assert a3.management_ip == ''


def test_asset_create_invalid_ip_raises_validation_error():
    # 1921.68.2.201 has 1921 > 255
    with pytest.raises(ValidationError) as exc_info:
        AssetCreate(asset_type='network_device', hostname='sw-1', management_ip='1921.68.2.201')
    assert "不是有效的 IPv4 或 IPv6 地址" in str(exc_info.value)

    # Invalid non-numeric octet
    with pytest.raises(ValidationError) as exc_info:
        AssetCreate(asset_type='network_device', hostname='sw-2', management_ip='192.168.1.abc')
    assert "不是有效的 IPv4 或 IPv6 地址" in str(exc_info.value)


def test_asset_update_ip_validation():
    # Valid update
    u1 = AssetUpdate(management_ip='10.20.30.40')
    assert u1.management_ip == '10.20.30.40'

    # None is allowed in update
    u2 = AssetUpdate(management_ip=None)
    assert u2.management_ip is None

    # Invalid update raises error
    with pytest.raises(ValidationError) as exc_info:
        AssetUpdate(management_ip='999.999.999.999')
    assert "不是有效的 IPv4 或 IPv6 地址" in str(exc_info.value)
