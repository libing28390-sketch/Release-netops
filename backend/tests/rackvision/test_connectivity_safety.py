import ipaddress

import pytest
from fastapi import HTTPException

from api import assets


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",
        "169.254.1.10",
        "169.254.169.254",
        "100.100.100.200",
        "0.0.0.0",
        "224.0.0.1",
        "198.51.100.10",
        "100.64.0.10",
        "not-an-ip",
    ],
)
def test_connectivity_target_rejects_ssrf_and_reserved_ranges(value):
    with pytest.raises(HTTPException) as exc_info:
        assets._validate_connectivity_target(value)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] in {
        "CONNECTIVITY_TARGET_INVALID",
        "CONNECTIVITY_TARGET_NOT_ALLOWED",
    }


def test_connectivity_target_allows_authorized_data_center_addresses():
    assert assets._validate_connectivity_target("192.168.56.10") == "192.168.56.10"
    assert assets._validate_connectivity_target("172.20.1.10") == "172.20.1.10"
    assert assets._validate_connectivity_target("fc00::10") == "fc00::10"
    public_ip = "8.8.8.8"
    assert assets._validate_connectivity_target(public_ip) == str(ipaddress.ip_address(public_ip))


@pytest.mark.parametrize("value", [0, -1, 65536, "not-a-port"])
def test_connectivity_port_is_bounded(value):
    with pytest.raises(HTTPException) as exc_info:
        assets._validate_connectivity_port(value)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "CONNECTIVITY_PORT_INVALID"


def test_connectivity_port_accepts_valid_port():
    assert assets._validate_connectivity_port("2222") == 2222
