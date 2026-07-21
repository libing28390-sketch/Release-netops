from __future__ import annotations

import os
from services.outbound_probe_service import _check_ip_matches_expected, detect_egress_ip

def test_check_ip_matches_expected():
    # Test single IP match
    assert _check_ip_matches_expected("202.96.128.8", "202.96.128.8") is True
    assert _check_ip_matches_expected("202.96.128.8", "202.96.128.9") is False

    # Test multiple comma-separated IPs
    assert _check_ip_matches_expected("202.96.128.8", "202.96.128.9, 202.96.128.8") is True
    assert _check_ip_matches_expected("202.96.128.8", "202.96.128.9, 202.96.128.10") is False

    # Test CIDR match
    assert _check_ip_matches_expected("202.96.128.5", "202.96.128.0/29") is True
    assert _check_ip_matches_expected("202.96.128.9", "202.96.128.0/29") is False

    # Test mixed config
    assert _check_ip_matches_expected("210.22.84.5", "202.96.128.0/29,210.22.84.5") is True

    # Empty inputs
    assert _check_ip_matches_expected("202.96.128.8", "") is True
    assert _check_ip_matches_expected("", "202.96.128.8") is True


def test_detect_egress_ip_override(monkeypatch):
    monkeypatch.setenv("OUTBOUND_PROBE_STATIC_EGRESS_IP", "1.2.3.4")
    res = detect_egress_ip()
    assert res["confirmed_ip"] == "1.2.3.4"
    assert res["consistent"] is True
