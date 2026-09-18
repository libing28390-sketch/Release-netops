import pytest
from backend.api.devices import clean_system_hostname


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
