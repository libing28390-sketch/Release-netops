from services.connection_profile import resolve_ssh_port


def test_resolve_ssh_port_prefers_management_port():
    assert resolve_ssh_port({"management_port": 2222, "port": 22}) == 2222


def test_resolve_ssh_port_accepts_compatibility_aliases():
    assert resolve_ssh_port({"port": "2200"}) == 2200
    assert resolve_ssh_port({"ssh_port": "2022"}) == 2022
    assert resolve_ssh_port({"target_port": "3022"}) == 3022


def test_resolve_ssh_port_defaults_on_invalid_values():
    assert resolve_ssh_port({"management_port": "bad"}) == 22
    assert resolve_ssh_port({"management_port": 70000}) == 22
    assert resolve_ssh_port({}) == 22
